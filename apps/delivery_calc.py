import streamlit as st
import pandas as pd
import configparser
import psycopg2
import os


def run():
            # --- НАСТРОЙКИ И ПОДКЛЮЧЕНИЕ ---
            st.title("Калькулятор стоимости доставки")
            
            config_path = os.path.join(os.getcwd(), "config.ini")
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')
            
            try:
                DATABASE_CREDS = config['Database']
            except KeyError:
                st.error("Файл config.ini не найден или не содержит секцию [Database]")
                st.stop()
            
            @st.cache_resource(ttl=3600)
            def get_connection():
                conn = psycopg2.connect(
                    host=DATABASE_CREDS['HOST'],
                    database=DATABASE_CREDS['DATABASE'],
                    user=DATABASE_CREDS['USER'],
                    password=DATABASE_CREDS['PASSWORD']
                )
                return conn
            
            @st.cache_data(ttl=600)
            def load_data_safe(query, params=None):
                conn = get_connection()
                return pd.read_sql(query, conn, params=params)
            
            @st.cache_data(ttl=600)
            def load_data(query):
                return load_data_safe(query)
            
            # --- ШАГ 1: ВЫБОР РЕЖИМА ВВОДА ---
            st.subheader("📥 Выбор режима ввода параметров груза")
            input_mode = st.radio(
                "Как будем вводить данные?",
                ["Вручную (пошагово)", "Загрузить из Excel"],
                index=0,
                help="Excel: колонки 'Клиент', 'Точка доставки', 'Фактический вес (кг)', 'Объём (м³)'"
            )
            
            cargo_data = {}
            selected_points = []
            excel_loaded = False
            selected_customer = None
            customer_id = None
            client_name = "Не указан" 
            
            # --- ШАГ 2: ЛОГИКА EXCEL ---
            if input_mode == "Загрузить из Excel":
                uploaded_file = st.file_uploader("Загрузите .xlsx файл", type=["xlsx"], key="excel_uploader")
                
                if uploaded_file is not None:
                    try:
                        df_upload = pd.read_excel(uploaded_file)
                        df_upload.columns = df_upload.columns.str.strip()
                        
                        required_cols = ["Клиент", "Точка доставки", "Фактический вес (кг)", "Объём (м³)"]
                        missing = [c for c in required_cols if c not in df_upload.columns]
                        
                        if missing:
                            st.error(f"Не хватает колонок: {', '.join(missing)}")
                        else:
                            df_upload = df_upload.dropna(subset=required_cols)
                            
                            # Валидация клиентов
                            df_customers = load_data("SELECT customer_id, customer_name FROM customers")
                            if df_customers.empty:
                                st.error("База пуста: нет списка клиентов для проверки.")
                            else:
                                valid_clients = set(df_customers["customer_name"].tolist())
                                df_upload = df_upload[df_upload["Клиент"].isin(valid_clients)]
                                
                                if df_upload.empty:
                                    st.error("Клиенты из файла не найдены в базе. Проверьте названия.")
                                else:
                                    # Заполняем данные: клиент берётся из каждой строки
                                    for _, row in df_upload.iterrows():
                                        point = str(row["Точка доставки"]).strip()
                                        w = max(0.0, float(row["Фактический вес (кг)"]))
                                        v = max(0.0, float(row["Объём (м³)"]))
                                        c_name = str(row["Клиент"]).strip()  # имя клиента из строки
                                        
                                        cargo_data[point] = {"weight": w, "volume": v, "client": c_name}
                                        if point not in selected_points:
                                            selected_points.append(point)
                                    
                                    excel_loaded = True
                                    client_name = df_upload["Клиент"].iloc[0]  # <-- для сводок можно взять первого, но в расчёте будем брать из cargo_data
                                    st.success(f"✅ Загружено {len(selected_points)} точек из Excel.")
                                    st.dataframe(df_upload[["Клиент", "Точка доставки", "Фактический вес (кг)", "Объём (м³)"]], use_container_width=True)
                                    
                    except Exception as e:
                        st.error(f"Ошибка чтения Excel: {e}")
            
            # --- ШАГ 3: ЛОГИКА РУЧНОГО ВВОДА ---
            if not excel_loaded:
                # Если Excel выбран, но файл не загружен — показываем подсказку
                if input_mode == "Загрузить из Excel" and not uploaded_file:
                    st.info("Загрузите файл Excel или переключитесь на ручной ввод.")
                    st.stop()
            
                # Ручной ввод (если режим ручной ИЛИ Excel не загрузился)
                if input_mode != "Загрузить из Excel" or (input_mode == "Загрузить из Excel" and uploaded_file):
                    try:
                        # Выбор клиента
                        df_customers = load_data("SELECT customer_id, customer_name FROM customers ORDER BY customer_name")
                        if df_customers.empty:
                            st.warning("Нет клиентов в базе.")
                            st.stop()
                        
                        customer_options = df_customers['customer_name'].tolist()
                        selected_customer = st.selectbox("1. Выберите клиента:", customer_options, index=0)
                        customer_id = df_customers.loc[df_customers['customer_name'] == selected_customer, 'customer_id'].iloc[0]
                        customer_id = int(customer_id)
                        
                        # <-- ГЛАВНОЕ ИЗМЕНЕНИЕ: для ручного режима client_name = selected_customer
                        client_name = selected_customer  
                        
                        st.info(f"Клиент: **{client_name}**")
            
                        # Выбор точек доставки
                        df_points = load_data_safe(
                            """
                            SELECT DISTINCT customer_delivery_point 
                            FROM customers_points 
                            WHERE customer_id = %s 
                            ORDER BY customer_delivery_point;
                            """,
                            params=(customer_id,)
                        )
            
                        if df_points.empty:
                            st.warning(f"У клиента «{client_name}» нет точек доставки.")
                            st.stop()
            
                        point_options = df_points['customer_delivery_point'].tolist()
                        selected_points = st.multiselect("2. Выберите точки доставки:", point_options)
            
                        if not selected_points:
                            st.info("Выберите хотя бы одну точку доставки.")
                            st.stop()
            
                        st.success(f"Выбрано точек: {len(selected_points)}")
            
                        # Ввод веса и объёма
                        st.subheader("3. Укажите вес и объём для каждой точки")
                        for point in selected_points:
                            col1, col2 = st.columns(2)
                            with col1:
                                weight = st.number_input(
                                    f"Вес для «{point}»", min_value=0.0, value=50.0, step=0.1, format="%.1f",
                                    key=f"w_{point}"
                                )
                            with col2:
                                volume = st.number_input(
                                    f"Объём для «{point}»", min_value=0.0, value=0.5, step=0.01, format="%.2f",
                                    key=f"v_{point}"
                                )
                            # <-- Для ручного ввода клиент общий, но кладём его в cargo_data для единообразия
                            cargo_data[point] = {'weight': weight, 'volume': volume, 'client': client_name}
            
                    except Exception as e:
                        st.error(f"Ошибка на этапе ручного ввода: {e}")
                        st.stop()
            
            # Проверка: есть ли вообще данные для расчёта
            if not cargo_data:
                st.warning("Нет данных о грузе. Невозможно выполнить расчёт.")
                st.stop()
            
            # --- БЛОК: ПРОВЕРКА И СВОДКА ТОЧЕК ДОСТАВКИ ---
            st.write("---")
            st.subheader("📋 Параметры груза (Сводка и проверка)")
            
            df_all_points = load_data_safe("SELECT DISTINCT customer_delivery_point FROM customers_points;")
            valid_points_set = set(df_all_points["customer_delivery_point"].tolist())
            
            accepted_points = []
            rejected_points = []
            
            for point, data in cargo_data.items():
                weight = data["weight"]
                volume = data["volume"]
            
                if point in valid_points_set:
                    accepted_points.append(point)
                else:
                    rejected_points.append((point, weight, volume, "Точка не найдена в базе"))
            
            if accepted_points:
                st.success(f"✅ Принято для расчёта: {len(accepted_points)} точек.")
                for p in accepted_points:
                    data = cargo_data[p]
                    st.write(f"  • {p}: {data['weight']} кг, {data['volume']} м³")
            else:
                st.warning("⚠️ Нет ни одной валидной точки доставки для расчёта!")
            
            if rejected_points:
                st.error(f"❌ Обнаружены ошибки: {len(rejected_points)} точек не найдены в базе.")
                
                for point, w, v, reason in rejected_points:
                    st.markdown(
                        f"  • <span style='color: red; font-weight: bold;'>{point}</span>: "
                        f"{w} кг, {v} м³ — {reason}",
                        unsafe_allow_html=True
                    )
                    del cargo_data[point]
            
            if not cargo_data:
                st.stop()
            
            # --- ШАГ 4: ВЫБОР ЭКСПЕДИТОРОВ ---
            df_forwarders = load_data("SELECT forwarder_id, forwarder_name FROM forwarders ORDER BY forwarder_name")
            if df_forwarders.empty:
                st.warning("В базе нет экспедиторов.")
                st.stop()
            
            forwarder_options = df_forwarders['forwarder_name'].tolist()
            selected_forwarders = st.multiselect("4. Выберите экспедиторов:", forwarder_options)
            if not selected_forwarders:
                st.info("Выберите хотя бы одного экспедитора.")
                st.stop()
            st.success(f"Выбраны экспедиторы: {', '.join(selected_forwarders)}")
            
            # --- ШАГ 5: ВЫБОР СКЛАДА ОТПРАВЛЕНИЯ ---
            df_starts = load_data("SELECT startpoint_name FROM start_points ORDER BY startpoint_name")
            if df_starts.empty:
                st.warning("В базе нет складов отправления.")
                st.stop()
            
            start_options = df_starts['startpoint_name'].tolist()
            selected_start_point = st.selectbox("5. Склад отправления:", start_options, index=0)
            st.info(f"Склад: **{selected_start_point}**")
            
            # --- ШАГ 6: КНОПКА РАСЧЁТА ---
            if st.button("🧮 Рассчитать стоимость доставки"):
                with st.spinner("Считаем тарифы..."):
                    results = []
                    
                    for point in cargo_data.keys():
                        cargo = cargo_data[point]
                        weight = cargo["weight"]
                        volume = cargo["volume"]
                        
                        # <-- БЕРЁМ КЛИЕНТА ИЗ cargo_data, а не из глобальной переменной
                        current_client = cargo.get("client", client_name)
            
                        for forwarder in selected_forwarders:
                            df_factor = load_data_safe(
                                """
                                SELECT DISTINCT volume_weight_factor
                                FROM v_tariffs
                                WHERE startpoint_name = %s
                                  AND customer_delivery_point = %s
                                  AND forwarder_name = %s
                                LIMIT 1;
                                """,
                                params=(selected_start_point, point, forwarder)
                            )
                            if df_factor.empty:
                                continue
                            
                            factor = df_factor['volume_weight_factor'].iloc[0]
                            chargeable_weight = max(weight, volume * factor)
            
                            df_tariff = load_data_safe(
                                f"""
                                SELECT price_per_kilo, min_delivery_price, additional_payment
                                FROM v_tariffs
                                WHERE startpoint_name = %s
                                  AND customer_delivery_point = %s
                                  AND forwarder_name = %s
                                  AND {chargeable_weight} BETWEEN min_weight AND max_weight
                                LIMIT 1;
                                """,
                                params=(selected_start_point, point, forwarder)
                            )
                            
                            if df_tariff.empty:
                                continue
                            
                            row = df_tariff.iloc[0]
                            price_per_kilo = row['price_per_kilo']
                            min_delivery_price = row['min_delivery_price']
                            additional_payment = row['additional_payment']
            
                            calculated_cost = chargeable_weight * price_per_kilo
                            cost = max(min_delivery_price, calculated_cost)
            
                            price_type = "По весу" if calculated_cost >= min_delivery_price else "Минимальная"
                            extra_flag = "Да, 16000 р. б.НДС за 1 рейс" if additional_payment > 0 else "Нет"
            
                            results.append({
                                "Клиент": current_client,  # <-- теперь здесь всегда правильное значение
                                "Склад отправления": selected_start_point,
                                "Точка доставки": point,
                                "Экспедитор": forwarder,
                                "Фактический вес (кг)": weight,
                                "Объём (м³)": volume,
                                "Платный вес (кг)": round(chargeable_weight, 2),
                                "Тариф за кг (руб)": price_per_kilo,
                                "Мин. цена (руб)": min_delivery_price,
                                "Тип цены": price_type,
                                "Доп. расходы": extra_flag,
                                "Стоимость (руб)": round(cost, 2)
                            })
            
                    if not results:
                        st.error("Не найдено подходящих тарифов для выбранных параметров.")
                    else:
                        df_results = pd.DataFrame(results)
                        
                        if "calc_results" not in st.session_state:
                            st.session_state.calc_results = {}
                        
                        st.session_state.calc_results[selected_start_point] = df_results
                        
                        st.success("Расчёт выполнен!")
                        st.subheader("Результаты расчёта")
                        st.dataframe(df_results, use_container_width=True)
            
                        st.subheader(f"Лучшие варианты по точкам (из {selected_start_point})")
                        best_rows = df_results.loc[
                            df_results.groupby("Точка доставки")["Стоимость (руб)"].idxmin()
                        ]
                        st.dataframe(best_rows[[
                            "Склад отправления", "Точка доставки", "Экспедитор",
                            "Платный вес (кг)", "Тип цены", "Доп. расходы", "Стоимость (руб)"
                        ]], use_container_width=True)
            
            
            # --- ШАГ 7: СРАВНЕНИЕ С ДРУГИМ СКЛАДОМ ---
            if "calc_results" in st.session_state and len(st.session_state.calc_results) >= 1:
                st.divider()
                st.subheader("🔄 Сравнение с другой точкой отправки")
                saved_points = list(st.session_state.calc_results.keys())
                st.caption(f"Уже рассчитано из: **{', '.join(saved_points)}**")
            
                all_start_points_df = load_data("SELECT startpoint_name FROM start_points ORDER BY startpoint_name")
                all_start_points = all_start_points_df['startpoint_name'].tolist()
                remaining_points = [p for p in all_start_points if p not in saved_points]
            
                if remaining_points:
                    second_point = st.selectbox(
                        "Выберите вторую точку отправления",
                        remaining_points,
                        key="second_start_point"
                    )
            
                    if st.button(f"🧮 Рассчитать из «{second_point}»"):
                        with st.spinner("Считаем тарифы..."):
                            results2 = []
                            for point in cargo_data.keys():
                                cargo = cargo_data[point]
                                weight = cargo["weight"]
                                volume = cargo["volume"]
                                current_client = cargo.get("client", client_name)  # Берём клиента из строки данных, если нет — из глобальной переменной
            
                                for forwarder in selected_forwarders:
                                    df_factor = load_data_safe(
                                        """
                                        SELECT DISTINCT volume_weight_factor
                                        FROM v_tariffs
                                        WHERE startpoint_name = %s
                                          AND customer_delivery_point = %s
                                          AND forwarder_name = %s
                                        LIMIT 1;
                                        """,
                                        params=(second_point, point, forwarder)
                                    )
                                    if df_factor.empty:
                                        continue
                                    
                                    factor = df_factor['volume_weight_factor'].iloc[0]
                                    chargeable_weight = max(weight, volume * factor)
            
                                    df_tariff = load_data_safe(
                                        f"""
                                        SELECT price_per_kilo, min_delivery_price, additional_payment
                                        FROM v_tariffs
                                        WHERE startpoint_name = %s
                                          AND customer_delivery_point = %s
                                          AND forwarder_name = %s
                                          AND {chargeable_weight} BETWEEN min_weight AND max_weight
                                        LIMIT 1;
                                        """,
                                        params=(second_point, point, forwarder)
                                    )
                                    
                                    if df_tariff.empty:
                                        continue
                                    
                                    row = df_tariff.iloc[0]
                                    price_per_kilo = row['price_per_kilo']
                                    min_delivery_price = row['min_delivery_price']
                                    additional_payment = row['additional_payment']
            
                                    calculated_cost = chargeable_weight * price_per_kilo
                                    cost = max(min_delivery_price, calculated_cost)
            
                                    price_type = "По весу" if calculated_cost >= min_delivery_price else "Минимальная"
                                    extra_flag = "Да, 16000 р. б.НДС за 1 рейс" if additional_payment > 0 else "Нет"
            
                                    results2.append({
                                        "Клиент": current_client,  # Теперь корректно подставляется и для Excel, и для ручного ввода
                                        "Склад отправления": second_point,
                                        "Точка доставки": point,
                                        "Экспедитор": forwarder,
                                        "Фактический вес (кг)": weight,
                                        "Объём (м³)": volume,
                                        "Платный вес (кг)": round(chargeable_weight, 2),
                                        "Тариф за кг (руб)": price_per_kilo,
                                        "Мин. цена (руб)": min_delivery_price,
                                        "Тип цены": price_type,
                                        "Доп. расходы": extra_flag,
                                        "Стоимость (руб)": round(cost, 2)
                                    })
            
                        if not results2:
                            st.error(f"Не найдено тарифов из «{second_point}» для выбранных параметров.")
                        else:
                            df_results2 = pd.DataFrame(results2)
                            st.session_state.calc_results[second_point] = df_results2
            
                            st.success(f"Расчёт из «{second_point}» выполнен!")
                            st.dataframe(df_results2, use_container_width=True)
            
            
            # --- ШАГ 8: ИТОГОВОЕ СРАВНЕНИЕ ВСЕХ СКЛАДОВ ---
            if "calc_results" in st.session_state and len(st.session_state.calc_results) >= 2:
                st.divider()
                st.subheader("📊 Сравнение по точкам отправления")
            
                all_dfs = list(st.session_state.calc_results.values())
                df_all = pd.concat(all_dfs, ignore_index=True)
            
                comparison_rows = []
            
                for point in df_all["Точка доставки"].unique():
                    df_point = df_all[df_all["Точка доставки"] == point]
            
                    best_per_warehouse = {}
                    for wh in df_point["Склад отправления"].unique():
                        df_wh = df_point[df_point["Склад отправления"] == wh]
                        best_idx = df_wh["Стоимость (руб)"].idxmin()
                        best_per_warehouse[wh] = df_wh.loc[best_idx]
            
                    warehouses = list(best_per_warehouse.keys())
                    row_data = {"Точка доставки": point}
            
                    prices = []
                    for wh in warehouses:
                        cost_val = best_per_warehouse[wh]["Стоимость (руб)"]
                        fwd = best_per_warehouse[wh]["Экспедитор"]
                        row_data[f"{wh} — лучший экспедитор"] = fwd
                        row_data[f"{wh} — цена (руб)"] = cost_val
                        prices.append(cost_val)
            
                    row_data["Разница (руб)"] = round(max(prices) - min(prices), 2)
            
                    cheapest_wh = warehouses[prices.index(min(prices))]
                    row_data["Выгоднее из"] = cheapest_wh
            
                    comparison_rows.append(row_data)
            
                df_comparison = pd.DataFrame(comparison_rows)
            
                st.caption("Сравнение лучших вариантов (самый дешёвый экспедитор по каждому складу):")
                st.dataframe(df_comparison, use_container_width=True)
            
                # Итог: суммарная стоимость по всем точкам для каждого склада
                st.subheader("💰 Итог: суммарная стоимость по всем точкам")
                totals = {}
                for wh in st.session_state.calc_results.keys():
                    df_wh = df_all[df_all["Склад отправления"] == wh]
                    # Берём минимальную стоимость по каждой точке для этого склада
                    best_total = df_wh.loc[
                        df_wh.groupby("Точка доставки")["Стоимость (руб)"].idxmin()
                    ]["Стоимость (руб)"].sum()
                    totals[wh] = round(best_total, 2)
            
                df_totals = pd.DataFrame([
                    {"Склад отправления": wh, "Итоговая стоимость (руб)": total}
                    for wh, total in totals.items()
                ]).sort_values("Итоговая стоимость (руб)")
            
                st.dataframe(df_totals, use_container_width=True)
            
                cheapest_total = df_totals.iloc[0]
                st.success(
                    f"✅ Выгоднее отправлять из «{cheapest_total['Склад отправления']}» — "
                    f"итого {cheapest_total['Итоговая стоимость (руб)']} руб."
                )


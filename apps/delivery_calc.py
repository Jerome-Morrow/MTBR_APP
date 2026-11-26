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

            # <-- ИЗМЕНЕНИЕ (шаг 1): расчёт вынесен в функцию.
            # Возвращает таблицу результатов для склада отправления
            # или None, если тарифов не нашлось.
            def calculate_from(start_point, cargo_data, selected_forwarders, client_name):
                results = []
                for point in cargo_data.keys():
                    cargo = cargo_data[point]
                    weight = cargo["weight"]
                    volume = cargo["volume"]
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
                            params=(start_point, point, forwarder)
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
                            params=(start_point, point, forwarder)
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
                            "Клиент": current_client,
                            "Склад отправления": start_point,
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

                return pd.DataFrame(results) if results else None

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
                                        c_name = str(row["Клиент"]).strip()

                                        cargo_data[point] = {"weight": w, "volume": v, "client": c_name}
                                        if point not in selected_points:
                                            selected_points.append(point)

                                    excel_loaded = True
                                    client_name = df_upload["Клиент"].iloc[0]
                                    st.success(f"✅ Загружено {len(selected_points)} точек из Excel.")
                                    st.dataframe(df_upload[["Клиент", "Точка доставки", "Фактический вес (кг)", "Объём (м³)"]], use_container_width=True)  # <-- поправлена обрезанная строка

                    except Exception as e:
                        st.error(f"Ошибка чтения Excel: {e}")


                        # --- ШАГ 3: ЛОГИКА РУЧНОГО ВВОДА ---
            if not excel_loaded:
                if input_mode == "Загрузить из Excel" and not uploaded_file:
                    st.info("Загрузите файл Excel или переключитесь на ручной ввод.")
                    st.stop()

                if input_mode != "Загрузить из Excel" or (input_mode == "Загрузить из Excel" and uploaded_file):
                    try:
                        df_customers = load_data("SELECT customer_id, customer_name FROM customers ORDER BY customer_name")
                        if df_customers.empty:
                            st.warning("Нет клиентов в базе.")
                            st.stop()

                        customer_options = df_customers['customer_name'].tolist()
                        selected_customer = st.selectbox("1. Выберите клиента:", customer_options, index=0)
                        customer_id = df_customers.loc[df_customers['customer_name'] == selected_customer, 'customer_id'].iloc[0]
                        customer_id = int(customer_id)

                        client_name = selected_customer
                        st.info(f"Клиент: **{client_name}**")

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

                        # <-- ИЗМЕНЕНИЕ: хранилище грузовых мест.
                        # places — словарь: точка -> список мест.
                        # Каждое место: вес (кг) и габариты в см (длина, ширина, высота).
                        # id нужен для стабильных ключей виджетов, чтобы при
                        # удалении/добавлении мест не подтягивались старые значения.
                        if "place_seq" not in st.session_state:
                            st.session_state.place_seq = 0
                        if "places" not in st.session_state:
                            st.session_state.places = {}

                        def new_place():
                            st.session_state.place_seq += 1
                            return {
                                "id": st.session_state.place_seq,
                                "weight": 50.0,   # кг
                                "l": 50.0,        # см
                                "w": 40.0,        # см
                                "h": 30.0,        # см
                            }

                        # Каждой выбранной точке — по одному месту по умолчанию.
                        # Точки, снятые с выбора, чистим из хранилища.
                        for point in selected_points:
                            if point not in st.session_state.places:
                                st.session_state.places[point] = [new_place()]
                        for p in list(st.session_state.places.keys()):
                            if p not in selected_points:
                                del st.session_state.places[p]

                        st.subheader("3. Грузовые места по каждой точке")
                        st.caption("Габариты вводятся в сантиметрах, объём считается автоматически.")

                        for point in selected_points:
                            st.markdown(f"**Точка: «{point}»**")
                            places = st.session_state.places[point]

                            total_weight = 0.0
                            total_volume = 0.0

                            for i, pl in enumerate(places):
                                cid = pl["id"]
                                col_w, col_l, col_wd, col_h, col_del = st.columns([2, 2, 2, 2, 1])
                                with col_w:
                                    pw = st.number_input(
                                        f"Вес (кг), место {i + 1}", min_value=0.0, step=0.1,
                                        format="%.1f", key=f"pl{cid}_w"
                                    )
                                with col_l:
                                    pl_len = st.number_input(
                                        f"Длина (см), место {i + 1}", min_value=0.0, step=1.0,
                                        format="%.1f", key=f"pl{cid}_l"
                                    )
                                with col_wd:
                                    pwid = st.number_input(
                                        f"Ширина (см), место {i + 1}", min_value=0.0, step=1.0,
                                        format="%.1f", key=f"pl{cid}_wd"
                                    )
                                with col_h:
                                    ph = st.number_input(
                                        f"Высота (см), место {i + 1}", min_value=0.0, step=1.0,
                                        format="%.1f", key=f"pl{cid}_h"
                                    )
                                with col_del:
                                    st.write("")  # выравнивание кнопки по строке
                                    if len(places) > 1 and st.button("✖", key=f"pl{cid}_del",
                                                                     help="Удалить это место"):
                                        places.remove(pl)
                                        st.rerun()

                                # сохраняем значения в хранилище и считаем объём места:
                                # см³ делим на 1 000 000, получаем м³
                                pl.update({"weight": pw, "l": pl_len, "w": pwid, "h": ph})
                                place_volume = (pl_len * pwid * ph) / 1_000_000.0

                                total_weight += pw
                                total_volume += place_volume

                                st.caption(
                                    f"Место {i + 1}: объём {place_volume:.3f} м³"
                                )

                            if st.button("➕ Добавить место", key=f"add_{point}"):
                                places.append(new_place())
                                st.rerun()

                            st.info(
                                f"Итого по точке «{point}»: "
                                f"{total_weight:.1f} кг, {total_volume:.3f} м³ "
                                f"(мест: {len(places)})"
                            )

                            # <-- дальше по коду всё как раньше: в cargo_data
                            # кладём УЖЕ посчитанные суммарные вес и объём
                            cargo_data[point] = {
                                "weight": total_weight,
                                "volume": total_volume,
                                "client": client_name,
                                "places": len(places),
                            }

                    except Exception as e:
                        st.error(f"Ошибка на этапе ручного ввода: {e}")
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

            # <-- ИЗМЕНЕНИЕ (шаг 2): хранилище расчётов.
            # calc_warehouses — список складов, по которым считали;
            # calc_results — свежие таблицы по каждому из них.
            if "calc_warehouses" not in st.session_state:
                st.session_state.calc_warehouses = []
            if "calc_results" not in st.session_state:
                st.session_state.calc_results = {}

            # --- ШАГ 5: ВЫБОР СКЛАДА ОТПРАВЛЕНИЯ ---
            df_starts = load_data("SELECT startpoint_name FROM start_points ORDER BY startpoint_code")
            if df_starts.empty:
                st.warning("В базе нет складов отправления.")
                st.stop()

            start_options = df_starts['startpoint_name'].tolist()
            selected_start_point = st.selectbox("5. Склад отправления:", start_options, index=0)
            st.info(f"Склад: **{selected_start_point}**")

            # <-- ИЗМЕНЕНИЕ (шаг 2): уже посчитанные склады показываем подписью,
            # чтобы было видно, что войдёт в пересчёт.
            if st.session_state.calc_warehouses:
                st.caption(f"Уже рассчитано из: **{', '.join(st.session_state.calc_warehouses)}**")

            # --- ШАГ 6: КНОПКА РАСЧЁТА ---
            # <-- ИЗМЕНЕНИЕ (шаги 2 и 3): кнопка добавляет склад в список
            # (или просто пересчитывает его повторно) и заново считает
            # ВСЕ склады из списка — включая любые точки, добавленные
            # после прошлого расчёта. None больше не возникает.
            if st.button("🧮 Рассчитать стоимость доставки"):
                with st.spinner("Считаем тарифы..."):
                    if selected_start_point not in st.session_state.calc_warehouses:
                        st.session_state.calc_warehouses.append(selected_start_point)

                    for wh in st.session_state.calc_warehouses:
                        st.session_state.calc_results[wh] = calculate_from(
                            wh, cargo_data, selected_forwarders, client_name
                        )

            # <-- ИЗМЕНЕНИЕ (шаг 2): таблицы рисуются из session_state,
            # поэтому не исчезают при перерисовке страницы.
            if st.session_state.calc_results:
                st.subheader("📄 Результаты расчёта")
                for wh, df_wh in st.session_state.calc_results.items():
                    if df_wh is None:
                        st.warning(f"Из «{wh}» не найдено подходящих тарифов.")
                        continue

                    with st.expander(f"Склад: «{wh}» — {len(df_wh)} вариантов", expanded=True):
                        st.dataframe(df_wh, use_container_width=True)

                        st.markdown(f"**Лучшие варианты по точкам (из {wh}):**")
                        best_rows = df_wh.loc[
                            df_wh.groupby("Точка доставки")["Стоимость (руб)"].idxmin()
                        ]
                        st.dataframe(best_rows[[
                            "Склад отправления", "Точка доставки", "Экспедитор",
                            "Платный вес (кг)", "Тип цены", "Доп. расходы", "Стоимость (руб)"
                        ]], use_container_width=True)

            # --- ШАГ 7 (бывший): ОТДЕЛЬНЫЙ БЛОК «ВТОРОЙ СКЛАД» УДАЛЁН.
            # Новый склад добавляется той же кнопкой: выбираете склад
            # в селектбоксе из шага 5 и жмёте «Рассчитать» — список
            # calc_warehouses пополняется, пересчёт идёт по всем.

            # --- ШАГ 8: ИТОГОВОЕ СРАВНЕНИЕ ВСЕХ СКЛАДОВ ---
            calculated_dfs = {wh: df for wh, df in st.session_state.calc_results.items() if df is not None}

            # <-- НОВОЕ: определяем, где встречаются доп. расходы
            def has_extra(flag_value):
                return str(flag_value).startswith("Да")

            extra_in_any = any(
                df_wh["Доп. расходы"].apply(has_extra).any()
                for df_wh in calculated_dfs.values()
            )

            if len(calculated_dfs) >= 2:
                st.divider()
                st.subheader("📊 Сравнение по точкам отправления")

                df_all = pd.concat(list(calculated_dfs.values()), ignore_index=True)
                warehouses = list(calculated_dfs.keys())
                all_points = df_all["Точка доставки"].unique()

                comparison_rows = []
                for point in all_points:
                    row_data = {"Точка доставки": point}
                    prices = []
                    extra_flags = []

                    for wh in warehouses:
                        df_wh = calculated_dfs[wh]
                        df_point = df_wh[df_wh["Точка доставки"] == point]

                        if df_point.empty:
                            row_data[f"{wh} — лучший экспедитор"] = "—"
                            row_data[f"{wh} — цена (руб)"] = "—"
                            continue

                        best = df_point.loc[df_point["Стоимость (руб)"].idxmin()]
                        # <-- НОВОЕ: пометка ⚠️ у экспедитора, если у лучшего варианта есть доп. расходы
                        fwd_label = best["Экспедитор"]
                        if has_extra(best["Доп. расходы"]):
                            fwd_label = f"{fwd_label} ⚠️"
                            extra_flags.append(True)
                        else:
                            extra_flags.append(False)

                        row_data[f"{wh} — лучший экспедитор"] = fwd_label
                        row_data[f"{wh} — цена (руб)"] = round(best["Стоимость (руб)"], 2)
                        prices.append(best["Стоимость (руб)"])

                    if len(prices) >= 2:
                        row_data["Разница (руб)"] = round(max(prices) - min(prices), 2)
                        row_data["Выгоднее из"] = warehouses[prices.index(min(prices))]
                    elif len(prices) == 1:
                        row_data["Разница (руб)"] = 0.0
                        row_data["Выгоднее из"] = "единственный вариант"
                    else:
                        continue

                    # <-- НОВОЕ: примечание по точке
                    row_data["Примечание"] = "⚠️ Есть доп. расходы" if any(extra_flags) else ""
                    comparison_rows.append(row_data)

                df_comparison = pd.DataFrame(comparison_rows)
                st.caption("Сравнение лучших вариантов (самый дешёвый экспедитор по каждому складу):")
                st.dataframe(df_comparison, use_container_width=True)

                # Итог: суммарная стоимость по всем точкам для каждого склада
                st.subheader("💰 Итог: суммарная стоимость по всем точкам")
                totals = []
                for wh, df_wh in calculated_dfs.items():
                    best_total = df_wh.loc[
                        df_wh.groupby("Точка доставки")["Стоимость (руб)"].idxmin()
                    ]
                    totals.append({
                        "Склад отправления": wh,
                        "Итоговая стоимость (руб)": round(best_total["Стоимость (руб)"].sum(), 2),
                        # <-- НОВОЕ: пометка, если по этому складу хотя бы у одной точки есть доп. расходы
                        "Примечание": "⚠️ Есть доп. расходы" if best_total["Доп. расходы"].apply(has_extra).any() else "",
                    })

                df_totals = pd.DataFrame(totals).sort_values("Итоговая стоимость (руб)")
                st.dataframe(df_totals, use_container_width=True)

                cheapest_total = df_totals.iloc[0]
                st.success(
                    f"✅ Выгоднее отправлять из «{cheapest_total['Склад отправления']}» — "
                    f"итого {cheapest_total['Итоговая стоимость (руб)']} руб."
                )

                # <-- НОВОЕ: общее примечание в самом конце
                if extra_in_any:
                    st.warning(
                        "⚠️ Не забудьте учесть дополнительные расходы: "
                        "16000 руб. без НДС за 1 рейс (см. пометки ⚠️ в таблицах выше)."
                    )

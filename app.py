import streamlit as st
import pandas as pd
import configparser
import psycopg2
import os

st.title("Расчёт стоимости доставки")

# --- ПОДКЛЮЧЕНИЕ ЧЕРЕЗ config.ini ---
config_path = os.path.join(os.getcwd(), "config.ini")
config = configparser.ConfigParser()
config.read(config_path, encoding='utf-8')
DATABASE_CREDS = config['Database']

@st.cache_resource
def get_connection():
    conn = psycopg2.connect(
        host=DATABASE_CREDS['HOST'],
        database=DATABASE_CREDS['DATABASE'],
        user=DATABASE_CREDS['USER'],
        password=DATABASE_CREDS['PASSWORD']
    )
    return conn

@st.cache_data
def load_data(query):
    conn = get_connection()
    return pd.read_sql(query, conn)

try:
    # --- ШАГ 3: Выбор клиента ---
    df_customers = load_data("SELECT customer_id, customer_name FROM customers ORDER BY customer_name;")
    if df_customers.empty:
        st.warning("Нет клиентов в базе.")
        st.stop()

    customer_options = df_customers['customer_name'].tolist()
    selected_customer = st.selectbox("1. Выберите клиента:", customer_options, index=0)
    customer_id = df_customers.loc[df_customers['customer_name'] == selected_customer, 'customer_id'].iloc[0]
    st.info(f"Клиент: **{selected_customer}**")

    # --- ШАГ 4: Выбор точек доставки ---
    df_points = load_data(
        f"SELECT DISTINCT customer_delivery_point "
        f"FROM customers_points "
        f"WHERE customer_id = {customer_id} "
        f"ORDER BY customer_delivery_point;"
    )

    if df_points.empty:
        st.warning(f"У клиента «{selected_customer}» нет точек доставки.")
        st.stop()

    point_options = df_points['customer_delivery_point'].tolist()
    selected_points = st.multiselect("2. Выберите точки доставки:", point_options)

    if not selected_points:
        st.info("Выберите хотя бы одну точку доставки, чтобы указать параметры груза.")
        st.stop()

    st.success(f"Выбрано точек: {len(selected_points)}")

    # --- ШАГ 5: Ввод веса и объёма для каждой точки ---
    st.subheader("3. Укажите вес и объём для каждой точки")
    
    cargo_data = {}  # {'Точка А': {'weight': ..., 'volume': ...}}

    for point in selected_points:
        col1, col2 = st.columns(2)
        
        with col1:
            weight = st.number_input(
                f"Вес для «{point}»",
                min_value=0.0,
                value=50.0,
                step=0.1,
                format="%.1f",
                help="Вес груза в кг"
            )
        
        with col2:
            volume = st.number_input(
                f"Объём для «{point}»",
                min_value=0.0,
                value=0.5,
                step=0.01,
                format="%.2f",
                help="Объём груза в м³"
            )

        cargo_data[point] = {'weight': weight, 'volume': volume}

    # Сводка по грузу
    st.write("Параметры груза:")
    for p, data in cargo_data.items():
        st.write(f"  • {p}: {data['weight']} кг, {data['volume']} м³")

         

    # --- ШАГ 5: Выбор экспедиторов ---
    # Таблица экспедиторов называется forwarders, а колонка с именем — forwarder_name
    df_forwarders = load_data("SELECT forwarder_id, forwarder_name FROM forwarders ORDER BY forwarder_name;")

    if df_forwarders.empty:
        st.warning("В таблице forwarders нет экспедиторов.")
        st.stop()

    forwarder_options = df_forwarders['forwarder_name'].tolist()

    selected_forwarders = st.multiselect(
        "4. Выберите экспедиторов для сравнения тарифов:",
        forwarder_options
    )

    if not selected_forwarders:
        st.info("Выберите хотя бы одного экспедитора, чтобы сравнить варианты доставки.")
        st.stop()

    st.success(f"Для расчёта выбраны экспедиторы: {', '.join(selected_forwarders)}")



    # --- ШАГ 6: Выбор точки отправления ---
    df_starts = load_data("SELECT startpoint_name FROM start_points ORDER BY startpoint_name;")

    if df_starts.empty:
        st.warning("В таблице start_points нет складов.")
        st.stop()

    start_options = df_starts['startpoint_name'].tolist()
    selected_start_point = st.selectbox(
        "5. Выберите склад отправления:",
        start_options,
        index=0
    )
    st.info(f"Склад отправления: **{selected_start_point}**")

        # --- ШАГ 7: Кнопка «Рассчитать» ---
    if st.button("🧮 Рассчитать стоимость доставки"):
        with st.spinner("Считаем тарифы..."):
            results = []

            for point in selected_points:
                cargo = cargo_data[point]
                weight = cargo["weight"]
                volume = cargo["volume"]

                for forwarder in selected_forwarders:
                    # --- ЗАПРОС 1: volume_weight_factor ---
                    df_factor = load_data(
                        f"""
                        SELECT DISTINCT volume_weight_factor
                        FROM v_tariffs
                        WHERE startpoint_name = '{selected_start_point}'
                          AND customer_delivery_point = '{point}'
                          AND forwarder_name = '{forwarder}'
                        LIMIT 1
                        """
                    )
                    if df_factor.empty:
                        continue

                    factor = df_factor['volume_weight_factor'].iloc[0]
                    chargeable_weight = max(weight, volume * factor)

                    # --- ЗАПРОС 2: тариф по диапазону ---
                    df_tariff = load_data(
                        f"""
                        SELECT price_per_kilo, min_delivery_price, additional_payment
                        FROM v_tariffs
                        WHERE startpoint_name = '{selected_start_point}'
                          AND customer_delivery_point = '{point}'
                          AND forwarder_name = '{forwarder}'
                          AND {chargeable_weight} BETWEEN min_weight AND max_weight
                        LIMIT 1
                        """
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
                    extra_flag = "Да" if additional_payment > 0 else "Нет"

                    results.append({
                        "Клиент": selected_customer,
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

                # Сохраняем результат в session_state
                if "calc_results" not in st.session_state:
                    st.session_state.calc_results = {}

                st.session_state.calc_results[selected_start_point] = df_results

                st.success("Расчёт выполнен!")
                st.subheader("Результаты расчёта")
                st.dataframe(df_results, use_container_width=True)

                st.subheader(f"Лучшие варианты по точкам, отправка из {selected_start_point}")
                best_rows = df_results.loc[
                    df_results.groupby("Точка доставки")["Стоимость (руб)"].idxmin()
                ]
                st.dataframe(best_rows[[
                    "Склад отправления", "Точка доставки", "Экспедитор",
                    "Платный вес (кг)", "Тип цены", "Доп. расходы", "Стоимость (руб)"
                ]], use_container_width=True)

    # --- ШАГ 7: Сравнение с другой точкой отправки ---
    if "calc_results" in st.session_state and len(st.session_state.calc_results) >= 1:
        st.divider()
        st.subheader("🔄 Сравнение с другой точкой отправки")

        saved_points = list(st.session_state.calc_results.keys())
        st.caption(f"Уже рассчитано из: **{', '.join(saved_points)}**")

        # Доступные склады, ещё не рассчитанные
        all_start_points_df = load_data("SELECT startpoint_name FROM start_points ORDER BY startpoint_name")
        all_start_points = all_start_points_df['startpoint_name'].tolist()
        remaining_points = [p for p in all_start_points if p not in saved_points]

        if remaining_points:
            second_point = st.selectbox(
                "Выберите вторую точку отправки для сравнения",
                remaining_points,
                key="second_start_point"
            )

            if st.button("🧮 Рассчитать из второй точки"):
                with st.spinner("Считаем тарифы..."):
                    results2 = []

                    for point in selected_points:
                        cargo = cargo_data[point]
                        weight = cargo["weight"]
                        volume = cargo["volume"]

                        for forwarder in selected_forwarders:
                            df_factor = load_data(
                                f"""
                                SELECT DISTINCT volume_weight_factor
                                FROM v_tariffs
                                WHERE startpoint_name = '{second_point}'
                                  AND customer_delivery_point = '{point}'
                                  AND forwarder_name = '{forwarder}'
                                LIMIT 1
                                """
                            )
                            if df_factor.empty:
                                continue

                            factor = df_factor['volume_weight_factor'].iloc[0]
                            chargeable_weight = max(weight, volume * factor)

                            df_tariff = load_data(
                                f"""
                                SELECT price_per_kilo, min_delivery_price, additional_payment
                                FROM v_tariffs
                                WHERE startpoint_name = '{second_point}'
                                  AND customer_delivery_point = '{point}'
                                  AND forwarder_name = '{forwarder}'
                                  AND {chargeable_weight} BETWEEN min_weight AND max_weight
                                LIMIT 1
                                """
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
                            extra_flag = "Да" if additional_payment > 0 else "Нет"

                            results2.append({
                                "Клиент": selected_customer,
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

    # --- ШАГ 8: Итоговое сравнение ---
    if "calc_results" in st.session_state and len(st.session_state.calc_results) >= 2:
        st.divider()
        st.subheader("📊 Сравнение по  точкам отправки")

        all_dfs = list(st.session_state.calc_results.values())
        df_all = pd.concat(all_dfs, ignore_index=True)

        # Для каждой точки доставки находим лучший вариант по каждому складу
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

        # Общая сумма по каждому складу
        st.caption("Сравнение лучших вариантов (самый дешёвый экспедитор по каждому складу):")
        st.dataframe(df_comparison, use_container_width=True)

        # Итог: суммарная стоимость по всем точкам для каждого склада
        st.subheader("💰 Итог: суммарная стоимость по всем точкам")
        totals = {}
        for wh in st.session_state.calc_results.keys():
            df_wh = df_all[df_all["Склад отправления"] == wh]
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

except Exception as e:
    st.error(f"Ошибка: {e}")
    st.code(str(e))
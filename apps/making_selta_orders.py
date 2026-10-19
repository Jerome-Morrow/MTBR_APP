# apps/inventory_check.py
import streamlit as st
import pandas as pd
import zipfile
import io
from datetime import datetime

def run():
    st.subheader("📦📦📦 Обработка заказов: тендер Сельта → готовые файлы для загрузки в  1С → ZIP")

    uploaded_file = st.file_uploader("Загрузите Excel‑файл с заказом по тендеру", type=["xlsx", "xls"])
    if not uploaded_file:
        st.info("Выберите файл .xlsx/.xls для обработки.")
        return

    with st.spinner("Читаю файл и обрабатываю данные..."):
        # Читаем файл в DataFrame
        df = pd.read_excel(uploaded_file)

        # --- ТВОЯ ЛОГИКА ПОДГОТОВКИ ДАННЫХ (без жёстких путей) ---

        # Определяем номер заказа и дату
        mask = df.astype(str).apply(
            lambda row: row.str.contains('на основании спецификации №', case=False, na=False).any(), axis=1)
        result = df[mask]
        result.dropna(axis='columns', inplace=True)

        if result.empty:
            st.error("Не удалось найти строку с «на основании спецификации №». Проверьте формат файла.")
            return

        main_order_number = result.iloc[0, 1]
        main_order_date = result.iloc[0, 3]

        # Находим строку заголовков
        start_row_mask = df[df.astype(str).apply(lambda x: x.str.contains('Номенклатура|Место поставки', na=False)).any(axis=1)]
        if start_row_mask.empty:
            st.error('Не найдена строка с заголовком «Номенклатура и Место поставки».')
            return
        start_row = start_row_mask.index[0]

        headers = df.iloc[start_row]
        df.columns = headers

        # Находим нижнюю границу данных
        end_row_mask = df[df.astype(str).apply(lambda x: x.str.contains('Итого сумма в EUR', na=False)).any(axis=1)]
        if end_row_mask.empty:
            st.warning('Строка «Итого сумма в EUR» не найдена — обрезаем до конца таблицы.')
            end_row = len(df)
        else:
            end_row = end_row_mask.index[0]

        cleaned_df = df.loc[start_row+1:end_row-1]
        cleaned_df = cleaned_df.dropna(axis='columns', how='all')
        cleaned_df = cleaned_df.dropna(axis=0, how='all').reset_index(drop=True)
        cleaned_df = cleaned_df.dropna(subset=['Номер заказа'])

        # Удаляем строки-заголовки внутри данных
        condition1 = cleaned_df.iloc[:, 0] == '№'
        condition2 = cleaned_df.iloc[:, 1] == 'Номер заказа'
        mask_inner = ~(condition1 & condition2)
        cleaned_df = cleaned_df[mask_inner].reset_index(drop=True)

        # Проверка нумерации
        if '№' in cleaned_df.columns:
            try:
                row_number = max(cleaned_df['№'].apply(lambda x: int(x)))
                len_df = len(cleaned_df)
                if row_number == len_df:
                    st.success(f"✅ Строк в первичном документе: {row_number}, очищенных: {len_df}. Статус: ОК.")
                else:
                    st.warning(f"⚠️ Строк в первичном документе: {row_number}, очищенных: {len_df}. Статус: ВНИМАНИЕ — данные отличаются.")
            except Exception:
                st.warning("Не удалось проверить нумерацию строк (возможно, столбец «№» содержит нечисловые значения).")

        # Группируем по заказам и формируем файлы
        unique_orders = cleaned_df['Номер заказа'].unique()
        st.write(f"Обработка документа {main_order_number}, количество заказов: {len(unique_orders)}")

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for unique_order in unique_orders:
                sub_df = cleaned_df.loc[cleaned_df['Номер заказа'] == unique_order]
                city = str(sub_df['Место поставки'].to_list()[0]).split()[1] if not sub_df['Место поставки'].empty else "unknown"
                delivery_date = str(sub_df['Дата поставки'].to_list()[0])

                sub_df=sub_df.loc[:, ['Катапожный номер аналога', 'Кол-во, шт','Сумма, с НДС']]
                sub_df.columns = ['Артикул', 'Количество', 'Цена руб. с НДС']

                # Создаём Excel в памяти
                excel_buffer = io.BytesIO()
                sub_df.to_excel(excel_buffer, index=False)
                excel_buffer.seek(0)

                file_name = f"{city} на {delivery_date} {unique_order} по {main_order_number} от {main_order_date}.xlsx"
                zipf.writestr(file_name, excel_buffer.read())

        buffer.seek(0)
        today = datetime.now().strftime('%Y-%m-%d')
        zip_filename = f"archive_{today}.zip"

        st.success("✅ ZIP‑архив сформирован!")
        st.download_button(
            label="📥 Скачать архив с обработанными файлами",
            data=buffer,
            file_name=zip_filename,
            mime="application/zip",
        )

import streamlit as st
import pandas as pd
import zipfile
import io
import os
from datetime import datetime
from pytils import numeral
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML


def fmt_date(dt):
    """Приводит дату к строке формата ДД.ММ.ГГГГ"""
    if pd.isna(dt) or dt is None:
        return ''
    if isinstance(dt, (pd.Timestamp, datetime)):
        return dt.strftime('%d.%m.%Y')
    return str(dt)


def load_orders(excel_file) -> list:
    """Загрузка Excel и формирование карточек заказов"""

    df = pd.read_excel(excel_file)

    # Пропускаем первые 8 строк (шапка отчёта и т.п.)
    df = df.iloc[8:]

    # Удаляем полностью пустые столбцы
    df = df.dropna(axis=1, how='all')
    df = df.fillna("")

    # Назначаем имена колонок
    df.columns = [
        'customer', 'start_date', 'end_date', 'truck', 'vin', 'mileage',
        'outer_doc_num', 'category', 'part_number', 'description',
        'partner', 'partner_adress', 'claim_number', 'hours', 'qty',
        'vat', 'sum', 'sum_with_vat'
    ]

    # Удаляем строку с итогами (если есть)
    df = df[df['customer'] != 'Итого'].reset_index(drop=True)

    # Приводим даты к формату datetime
    for col in ['start_date', 'end_date']:
        df[col] = pd.to_datetime(df[col], format='%d.%m.%Y', errors='coerce')

    # Конвертируем числовые колонки
    numeric_cols = ['hours', 'qty', 'vat', 'sum', 'sum_with_vat']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Формирование карточек заказов
    orders = []

    for doc_num, group in df.groupby('outer_doc_num'):
        first_row = group.iloc[0]
        cat_norm = group['category'].astype(str).str.strip().str.lower()

        # Работы
        works_df = group[cat_norm == 'работы'].copy()
        if not works_df.empty and (works_df['hours'] > 0).any():
            works_df['price_per_hour'] = round((works_df['sum'] / works_df['hours']), 2)
        else:
            works_df['price_per_hour'] = 0.0

        # Материалы/запчасти
        parts_df = group[~(cat_norm == 'работы')].copy()
        if not parts_df.empty and (parts_df['qty'] > 0).any():
            parts_df['price_per_unit'] = round((parts_df['sum'] / parts_df['qty']), 2)
        else:
            parts_df['price_per_unit'] = 0.0

        # Конвертация в список словарей — обязательно для Jinja
        works = works_df.to_dict('records') if not works_df.empty else []
        parts = parts_df.to_dict('records') if not parts_df.empty else []

        # Суммы без НДС
        sum_works = sum(r['sum'] for r in works) if works else 0.0
        sum_parts = sum(r['sum'] for r in parts) if parts else 0.0
        total_sum = sum_works + sum_parts

        # Суммы с НДС
        sum_works_vat = sum(r['sum_with_vat'] for r in works) if works else 0.0
        sum_parts_vat = sum(r['sum_with_vat'] for r in parts) if parts else 0.0
        total_sum_vat = sum_works_vat + sum_parts_vat

        order_card = {
            'info': {
                'outer_doc_num': doc_num,
                'customer': first_row['customer'],
                'start_date': fmt_date(first_row['start_date']),
                'end_date': fmt_date(first_row['end_date']),
                'truck': first_row['truck'],
                'vin': first_row['vin'],
                'mileage': first_row['mileage'],
                'partner': first_row['partner'],
                'partner_adress': first_row['partner_adress'],
                'claim_number': first_row['claim_number'],
            },
            'works': works,
            'parts': parts,
            'totals': {
                'sum_works': sum_works,
                'sum_parts': sum_parts,
                'total_sum': total_sum,
            },
            'totals_vat': {
                'sum_works_vat': sum_works_vat,
                'sum_parts_vat': sum_parts_vat,
                'total_sum_vat': total_sum_vat,
                'total_vat_words': numeral.rubles(total_sum_vat),
                'vat': round((total_sum_vat - (total_sum_vat / 1.22)), 2),
            },
        }
        orders.append(order_card)

    return orders


def run():
    st.subheader("🧾 Заказ-наряды: Excel → PDF → ZIP")

    uploaded_file = st.file_uploader("Загрузите Excel-файл с заказ-нарядами", type=["xlsx", "xls"])
    if not uploaded_file:
        st.info("Выберите файл .xlsx/.xls для обработки.")
        return

    with st.spinner("Читаю файл и обрабатываю данные..."):
        # Формируем карточки заказов
        orders = load_orders(uploaded_file)

        if not orders:
            st.error("Не удалось сформировать ни одного заказ-наряда. Проверьте формат файла.")
            return

        st.success(f"✅ Сформировано карточек заказов: {len(orders)}")

        # Путь к шаблону — относительно текущего файла (apps/resources/)
        template_dir = os.path.join(os.path.dirname(__file__), "resources")
        template_path = os.path.join(template_dir, "order_template.html")

        if not os.path.exists(template_path):
            st.error(f"Файл шаблона не найден: {template_path}")
            return

        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template("order_template.html")

        # Генерируем PDF и сразу складываем в ZIP-архив в памяти
        progress = st.progress(0)
        errors = []

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, order in enumerate(orders, start=1):
                doc_num = order['info']['outer_doc_num']
                try:
                    html_content = template.render(**order)

                    pdf_buffer = io.BytesIO()
                    HTML(string=html_content).write_pdf(pdf_buffer)

                    customer = order['info']['customer'].replace('"', '_').replace('ООО _', '')
                    truck = order['info']['truck']
                    file_name = f"{customer}{truck}_{doc_num}.pdf"

                    zipf.writestr(file_name, pdf_buffer.getvalue())
                except Exception as e:
                    errors.append(f"Заказ {doc_num}: {e}")

                progress.progress(i / len(orders))

        buffer.seek(0)
        today = datetime.now().strftime('%Y-%m-%d')
        zip_filename = f"orders_{today}.zip"

    if errors:
        st.warning("⚠️ Не удалось сформировать:\n" + "\n".join(errors))

    st.success("✅ ZIP-архив сформирован!")
    st.download_button(
        label="📥 Скачать архив с заказ-нарядами",
        data=buffer,
        file_name=zip_filename,
        mime="application/zip",
    )

import streamlit as st
import os

st.set_page_config(
    page_title="МТБР apps",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Стили для больших кнопок
st.markdown("""
<style>
    .big-button {
        display: block;
        width: 100%;
        padding: 100px 80px;
        font-size: 24px;
        font-weight: 600;
        border-radius: 16px;
        text-align: center;
        background-color: var(--st-primary-color);
        color: white;
        border: none;
        cursor: pointer;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        transition: transform 0.15s, box-shadow 0.15s;
    }
    .big-button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0,0,0,0.2);
    }
</style>
""", unsafe_allow_html=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
img_path = os.path.join(BASE_DIR, "logo.png")

# --- ГЛАВНЫЙ ЗАГОЛОВОК (самый первый и крупный) ---
col_img, col_txt = st.columns([1, 8])  # картинка слева, заголовок справа

with col_img:
    if os.path.exists(img_path):
        # 150px — это как раз «иконка рядом с заголовком», не перекрывает текст
        st.image(img_path, width=150)
    else:
        # Если картинки нет — показываем эмодзи, чтобы страница не ломалась
        st.markdown("<div style='font-size:150px; line-height:1.2;'>🚀</div>", unsafe_allow_html=True)

with col_txt:
    # Самый крупный заголовок — h1 через markdown
    st.markdown("# Панель мини-приложений")
    st.subheader("Выберите инструмент для работы")



# 5 колонок: [отступ, кнопка 1, кнопка 2, кнопка 3, отступ]
col1, col2, col3, col4, col5 = st.columns([1, 3, 3, 3, 1])

with col2:
    if st.button("🔢 Калькулятор доставки", key="btn_calc", use_container_width=True):
        st.session_state["app"] = "calc_delivery"
        st.rerun()

with col3:
    if st.button("📦 Обработка тендера Сельта", key="btn_inv", use_container_width=True):
        st.session_state["app"] = "inventory_check"
        st.rerun()

with col4:
    if st.button("🧾 Заказ-наряды в PDF", key="btn_order_pdf", use_container_width=True):
        st.session_state["app"] = "order_pdf"
        st.rerun()        

current_app = st.session_state.get("app")


if current_app == "calc_delivery":
    from apps.delivery_calc import run
    run()
elif current_app == "inventory_check":
    from apps.making_selta_orders import run
    run()
elif current_app == "order_pdf":
    from apps.order_pdf_generator import run
    run()
else:
    st.info("Нажмите на кнопку, чтобы запустить приложение.")
from dotenv import load_dotenv
import os
import streamlit as st
import psycopg2
import random
from psycopg2.extras import RealDictCursor
from datetime import datetime

load_dotenv()

st.set_page_config(page_title="تصنيف التغريدات", layout="centered")

st.markdown("""
    <style>
    html, body, [class*="css"]  {
        direction: rtl;
        text-align: right;
        font-family: "Arial", sans-serif;
        background-color: white !important;
        color: black;
    }
    </style>
""", unsafe_allow_html=True)

def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT'),
    )

def create_annotation_table():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tweet_annotations (
                    id SERIAL PRIMARY KEY,
                    tweet_id TEXT,
                    tweet_internal_id BIGINT,
                    user_id INT,
                    is_hate_speech BOOLEAN,
                    main_category TEXT,
                    sub_category TEXT,
                    sentiment TEXT,
                    status TEXT DEFAULT 'classified',
                    annotated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        conn.commit()

def fetch_random_tweet(user_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                WITH remaining AS (
                    SELECT id
                    FROM twitter_hate_api_365
                    WHERE id NOT IN (
                        SELECT tweet_id FROM tweet_annotations WHERE user_id = %s
                    )
                    LIMIT 1000
                )
                SELECT t.*
                FROM twitter_hate_api_365 t
                JOIN remaining r ON t.id = r.id
                OFFSET floor(random() * 1000)::int
                LIMIT 1;
            """, (user_id,))
            tweet = cur.fetchone()
    return tweet

# حفظ التصنيف
def save_annotation(tweet_id, internal_id, user_id, is_hate, main_cat, sub_cat, sentiment):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tweet_annotations (
                    tweet_id, tweet_internal_id, user_id,
                    is_hate_speech, main_category, sub_category, sentiment
                ) VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (tweet_id, internal_id, user_id, is_hate, main_cat, sub_cat, sentiment))
        conn.commit()

page = st.sidebar.selectbox("📁 اختر الصفحة", ["التصنيف", "لوحة المتابعة"])

if page == "التصنيف":
    st.title("📊 تصنيف التغريدات")
    create_annotation_table()

    if "user_id" not in st.session_state:
        with st.form("auth_form"):
            user_id_input = st.number_input("🧑 رقم المصنف:", min_value=1, step=1)
            user_password = st.text_input("🔐 كلمة المرور:", type="password")
            submitted = st.form_submit_button("تسجيل الدخول")

        if submitted:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT password FROM annotators WHERE user_id = %s", (user_id_input,))
                    row = cur.fetchone()
                    if row and row[0] == user_password:
                        st.session_state.user_id = user_id_input
                        st.success("✅ تم تسجيل الدخول بنجاح")
                        st.rerun()
                    else:
                        st.error("🚫 رقم المصنف أو كلمة المرور غير صحيحة.")
        st.stop()

    user_id = st.session_state.user_id

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tweet_annotations WHERE user_id = %s;", (user_id,))
            classified_count = cur.fetchone()[0]

    st.markdown(f"🔢 **عدد التغريدات التي صنفتها:** {classified_count}")
    st.markdown(f"🆔 **رمز المصنف:** `{abs(hash(user_id)) % 100000}`")

    if "current_tweet" not in st.session_state:
        st.session_state.current_tweet = fetch_random_tweet(user_id)

    tweet = st.session_state.current_tweet

    if tweet:
        st.markdown("### 📝 التغريدة:")
        st.write(tweet["text"])
        st.markdown(f"🔍 **كلمة البحث:** `{tweet.get('search_term', '')}`")

        is_hate_options = {"نعم": "Yes", "لا": "No"}
        is_hate_arabic = st.radio("هل تحتوي على عنف إلكتروني؟", list(is_hate_options.keys()))
        is_hate = is_hate_options[is_hate_arabic]

        main_cat, sub_cat, sentiment = None, None, None

        if is_hate == "Yes":
            is_hate_flag = True
            main_categories = {
                "التنمر الإلكتروني": "Cyberbullying",
                "خطاب الكراهية عبر الإنترنت": "Online Hate speech",
            }
            main_cat_arabic = st.selectbox("🧩 التصنيف الرئيسي:", list(main_categories.keys()))
            main_cat = main_categories[main_cat_arabic]

            if main_cat == "Online Hate speech":
                sub_categories = {
                    "التحريض على العنف": "Incitement to Violence",
                    "التمييز على اساس الجنس": "Gender Discrimination",
                    "التمييز الوطني": "National Discrimination",
                    "التمييز الطبقي": "Social Class Discrimination",
                    "التمييز القبلي": "Tribal Discrimination",
                    "التمييز الديني": "Religion Discrimination",
                    "التمييز الإقليمي": "Regional Discrimination",
                    "كراهية عامة": "General Hate"
                }
                sub_cat_arabic = st.selectbox("🧷 التصنيف الفرعي:", list(sub_categories.keys()))
                sub_cat = sub_categories[sub_cat_arabic]
        else:
            is_hate_flag = False
            main_cat = 'Benign'
            sentiments = {
                "إيجابي": "Positive",
                "محايد": "Neutral",
                "سلبي": "Negative"
            }
            sentiment_arabic = st.selectbox("🎭 الشعور:", list(sentiments.keys()))
            sentiment = sentiments[sentiment_arabic]

        if st.button("✅ حفظ التصنيف"):
            save_annotation(
                tweet["id"],
                tweet.get("internal_id") or tweet.get("rowid") or None,
                user_id,
                is_hate_flag,
                main_cat,
                sub_cat,
                sentiment
            )
            st.success("✅ تم الحفظ! جاري تحميل تغريدة جديدة...")
            st.session_state.pop("current_tweet")
            st.rerun()

        if st.button("❌ تعذر التصنيف"):
            save_annotation(
                tweet["id"],
                tweet.get("internal_id") or tweet.get("rowid") or None,
                user_id,
                False,  # أو None حسب رؤيتك، لأنه ليس عنف إلكتروني
                "Not Classifiable",  # main_category
                None,  # sub_category
                None  # sentiment
            )
            # with get_db_connection() as conn:
            #     with conn.cursor() as cur:
            #         cur.execute(
            #             "UPDATE tweet_annotations SET status = 'not_classifiable' WHERE tweet_id = %s AND user_id = %s;",
            #             (tweet["id"], user_id)
            #         )
            #     conn.commit()
            st.warning("⚠️ تم تسجيل التغريدة كغير قابلة للتصنيف.")
            st.session_state.pop("current_tweet")
            st.rerun()

    else:
        st.info("🎉 لا توجد تغريدات غير مصنفة متبقية.")

elif page == "لوحة المتابعة":
    st.title("📈 لوحة متابعة المصنفين")

    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
    if "admin_authenticated" not in st.session_state:
        password = st.text_input("🔐 أدخل كلمة المرور:", type="password")
        if password:
            if password == ADMIN_PASSWORD:
                st.session_state.admin_authenticated = True
                st.success("✅ تم تسجيل الدخول كمسؤول")
                st.rerun()
            else:
                st.error("🚫 كلمة المرور غير صحيحة.")
        st.stop()


    # with get_db_connection() as conn:
    #     with conn.cursor(cursor_factory=RealDictCursor) as cur:
    #         cur.execute("""
    #             SELECT user_id, COUNT(*) AS tweets_annotated
    #             FROM tweet_annotations
    #             GROUP BY user_id
    #             ORDER BY tweets_annotated DESC;
    #         """)
    #         stats = cur.fetchall()
    #
    #         cur.execute("SELECT COUNT(*) FROM twitter_hate_api_365;")
    #         total = cur.fetchone()["count"]
    #
    # st.markdown(f"📦 إجمالي التغريدات: **{total}**")
    # st.markdown("### 👥 التقدم حسب المصنفين:")
    #
    # for row in stats:
    #     st.markdown(f"- 🧑 المصنف {row['user_id']}: **{row['tweets_annotated']}** تغريدة")

    import pandas as pd

    # st.markdown("---")
    st.markdown("## 🧾 تحليل التصنيفات حسب النوع")

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1️⃣ إجمالي عدد التغريدات لكل main_category لكل مصنف
            cur.execute("""
                SELECT user_id, main_category, COUNT(*) AS count
                FROM tweet_annotations
                GROUP BY user_id, main_category;
            """)
            user_main_stats = cur.fetchall()

            # 2️⃣ التصنيفات الفرعية والشعور لكل مصنف
            cur.execute("""
                SELECT user_id, COALESCE(sub_category, sentiment) AS category_detail, COUNT(*) AS count
                FROM tweet_annotations
                GROUP BY user_id, category_detail;
            """)
            user_detail_stats = cur.fetchall()

    df_main = pd.DataFrame(user_main_stats)
    df_main_pivot = df_main.pivot_table(
        index="main_category",
        columns="user_id",
        values="count",
        fill_value=0
    ).sort_index()

    df_main_pivot.loc["✅ الإجمالي"] = df_main_pivot.sum()
    st.subheader("📊 عدد التصنيفات الرئيسية لكل مصنف")
    st.dataframe(df_main_pivot, use_container_width=True)

    df_detail = pd.DataFrame(user_detail_stats)
    df_detail_pivot = df_detail.pivot_table(
        index="category_detail",
        columns="user_id",
        values="count",
        fill_value=0
    ).sort_index()

    df_detail_pivot.loc["✅ الإجمالي"] = df_detail_pivot.sum()
    st.subheader("📊 عدد التصنيفات الفرعية / المشاعر لكل مصنف")
    st.dataframe(df_detail_pivot, use_container_width=True)




from dotenv import load_dotenv
import os
import streamlit as st
import psycopg2
import random
from psycopg2.extras import RealDictCursor
from datetime import datetime
import emoji

# ✨ أنواع متوافقة مع 3.7 / 3.8
from typing import List, Dict, Any, Optional

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

# ------------------------------------------------------------------
# 🛠️  إعداد الاتصال بقاعدة البيانات
# ------------------------------------------------------------------
def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT'),
    )

# ------------------------------------------------------------------
# 🛡️  إنشاء جدول التصنيفات إن لم يكن موجودًا
# ------------------------------------------------------------------
def create_annotation_table() -> None:
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

# ------------------------------------------------------------------
# ⚡️ جلب تغريدة عشوائية بأقل ضغط على القاعدة
# ------------------------------------------------------------------
def fetch_random_tweet(user_id: int,
                       attempts: int = 8) -> Optional[Dict[str, Any]]:
    """
    تجلب تغريدة غير مصنَّفة للمستخدم بدون OFFSET/ORDER BY random().
    الإصلاح يشمل:
      • تحويل id إلى نص داخل شرط NOT EXISTS لتطابق الأنواع.
      • تحويل min_id/max_id إلى int قبل استخدامها.
    """
    with get_db_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # حدود المدى
        cur.execute("""
            SELECT MIN(id) AS min_id, MAX(id) AS max_id
            FROM final_clean_tweets2
            WHERE is_deleted = FALSE;
        """)
        row = cur.fetchone()
        if not row or row["min_id"] is None:
            return None

        # نحولهما إلى int للتوافق مع random.randint
        min_id = int(row["min_id"])
        max_id = int(row["max_id"])

        for _ in range(attempts):
            rand_id = random.randint(min_id, max_id)

            cur.execute("""
                SELECT  t.*
                FROM    final_clean_tweets2 t
                WHERE   t.id >= %s
                  AND   t.is_deleted = FALSE
                  AND   NOT EXISTS (
                          SELECT 1
                          FROM   tweet_annotations a
                          WHERE  a.tweet_id = t.id::text   -- 👈 تحويل id إلى نص
                            AND  a.user_id  = %s
                        )
                ORDER BY t.id
                LIMIT 1;
            """, (rand_id, user_id))

            tweet = cur.fetchone()
            if tweet:
                return tweet

        return None

# ------------------------------------------------------------------
# 💾 حفظ التصنيف في جدول tweet_annotations
# ------------------------------------------------------------------
def save_annotation(tweet_id: str, internal_id: int, user_id: int,
                    is_hate: bool, main_cat: str,
                    sub_cat: Optional[str], sentiment: Optional[str]) -> None:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tweet_annotations (
                    tweet_id, tweet_internal_id, user_id,
                    is_hate_speech, main_category, sub_category, sentiment
                ) VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (tweet_id, internal_id, user_id,
                  is_hate, main_cat, sub_cat, sentiment))
        conn.commit()
def delete_tweet(tweet_id: int, user_id: int) -> None:
    """
    يحدِّث is_deleted = TRUE في الجدول الأصلي
    ويسجِّل العملية في tweet_annotations كـ status='deleted'.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # ➊ حذف منطقي في جدول التغريدات
            cur.execute(
                "UPDATE final_clean_tweets2 SET is_deleted = TRUE WHERE id = %s;",
                (tweet_id,)
            )
            # ➋ توثيق الحذف في جدول التصنيفات
            cur.execute("""
                INSERT INTO tweet_annotations (
                    tweet_id, tweet_internal_id, user_id,
                    is_hate_speech, main_category, sub_category, sentiment, status
                ) VALUES (%s, %s, %s, false, 'deleted', 'deleted', NULL, 'deleted');
            """, (tweet_id, tweet_id, user_id))
        conn.commit()

# ------------------------------------------------------------------
# 📋 واجهة Streamlit
# ------------------------------------------------------------------
page = st.sidebar.selectbox("📁 اختر الصفحة", ["التصنيف", "لوحة المتابعة"])

# =============== صفحة التصنيف ===============
if page == "التصنيف":
    st.title("📊 تصنيف التغريدات")
    create_annotation_table()

    # تسجيل الدخول للمصنِّف
    if "user_id" not in st.session_state:
        with st.form("auth_form"):
            user_id_input = st.number_input("🧑 رقم المصنف:", min_value=1, step=1)
            user_password = st.text_input("🔐 كلمة المرور:", type="password")
            submitted = st.form_submit_button("تسجيل الدخول")

        if submitted:
            with get_db_connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT password FROM annotators WHERE user_id = %s",
                            (user_id_input,))
                row = cur.fetchone()
                if row and row[0] == user_password:
                    st.session_state.user_id = user_id_input
                    st.success("✅ تم تسجيل الدخول بنجاح")
                    st.rerun()
                else:
                    st.error("🚫 رقم المصنف أو كلمة المرور غير صحيحة.")
        st.stop()

    user_id = st.session_state.user_id

    # عدّاد التصنيفات
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM tweet_annotations WHERE user_id = %s;",
                    (user_id,))
        classified_count = cur.fetchone()[0]

    st.markdown(f"🔢 **عدد التغريدات التي صنفتها:** {classified_count}")
    st.markdown(f"🆔 **رمز المصنف:** `{abs(hash(user_id)) % 100000}`")

    # جلب التغريدة الحالية أو تحميل جديدة
    if "current_tweet" not in st.session_state:
        st.session_state.current_tweet = fetch_random_tweet(user_id)

    tweet = st.session_state.current_tweet

    if tweet:
        st.markdown("### 📝 التغريدة:")
        converted = emoji.emojize(tweet["clean_text"], language='alias')
        st.write(converted)
        st.markdown(f"🔍 **كلمة البحث:** `{tweet.get('search_term', '')}`")

        # اختيار التصنيف
        is_hate_options = {"نعم": True, "لا": False}
        is_hate_arabic = st.radio("هل تحتوي على عنف إلكتروني؟",
                                  list(is_hate_options.keys()))
        is_hate_flag = is_hate_options[is_hate_arabic]

        main_cat, sub_cat, sentiment = None, None, None

        if is_hate_flag:
            main_categories = {
                "التنمر الإلكتروني": "Cyberbullying",
                "خطاب الكراهية عبر الإنترنت": "Online Hate speech",
            }
            main_cat_arabic = st.selectbox("🧩 التصنيف الرئيسي:",
                                           list(main_categories.keys()))
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
                sub_cat_arabic = st.selectbox("🧷 التصنيف الفرعي:",
                                              list(sub_categories.keys()))
                sub_cat = sub_categories[sub_cat_arabic]
        else:
            main_cat = "Benign"
            sentiments = {
                "إيجابي": "Positive",
                "محايد": "Neutral",
                "سلبي": "Negative"
            }
            sentiment_arabic = st.selectbox("🎭 الشعور:", list(sentiments.keys()))
            sentiment = sentiments[sentiment_arabic]

        # زر الحفظ
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

        # زر غير قابلة للتصنيف
        if st.button("❌ تعذّر التصنيف"):
            save_annotation(
                tweet["id"],
                tweet.get("internal_id") or tweet.get("rowid") or None,
                user_id,
                False,
                "Not Classifiable",
                None,
                None
            )
            st.warning("⚠️ تم تسجيل التغريدة كغير قابلة للتصنيف.")
            st.session_state.pop("current_tweet")
            st.rerun()
        # زر حذف التغريدة نهائيًا
        if st.button("🗑️ حذف التغريدة"):
            delete_tweet(tweet["id"], user_id)
            st.warning("🚫 تم وضع is_deleted = TRUE وتسجيل الحذف.")
            st.session_state.pop("current_tweet")
            st.rerun()

    else:
        st.info("🎉 لا توجد تغريدات غير مصنفة متبقية.")

# =============== لوحة المتابعة ===============
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

    import pandas as pd

    st.markdown("## 🧾 تحليل التصنيفات حسب النوع")

    with get_db_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT user_id, main_category, COUNT(*) AS count
            FROM tweet_annotations
            GROUP BY user_id, main_category;
        """)
        user_main_stats = cur.fetchall()

        cur.execute("""
            SELECT user_id,
                   COALESCE(sub_category, sentiment) AS category_detail,
                   COUNT(*) AS count
            FROM tweet_annotations
            GROUP BY user_id, category_detail;
        """)
        user_detail_stats = cur.fetchall()

    # Pivot – التصنيفات الرئيسية
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

    # Pivot – التصنيفات الفرعية / المشاعر
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

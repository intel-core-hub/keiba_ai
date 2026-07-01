# dashboard/streamlit_app.py

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt


st.title("🏇 Keiba AI Dashboard")

# ----------------------------------
# ログ読み込み
# ----------------------------------

df = pd.read_csv("derived/bets.csv")

st.write("### 最新ログ")
st.dataframe(df.tail(20))

# ----------------------------------
# 資金推移
# ----------------------------------

st.write("### Bankroll Curve")

df["bankroll_curve"] = df["profit"].cumsum()

fig, ax = plt.subplots()
ax.plot(df["bankroll_curve"])

ax.set_xlabel("Bet")
ax.set_ylabel("Profit")

st.pyplot(fig)

# ----------------------------------
# 的中率
# ----------------------------------

hit_rate = df["hit"].mean()

st.metric("Hit Rate", f"{hit_rate:.2%}")

# ----------------------------------
# Brier Score
# ----------------------------------

df = df.dropna()

brier = ((df["probability"] - df["hit"]) ** 2).mean()

st.metric("Brier Score", round(brier, 4))

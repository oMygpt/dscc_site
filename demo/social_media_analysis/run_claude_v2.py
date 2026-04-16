import pandas as pd, numpy as np
from scipy.stats import chi2_contingency, pearsonr
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, accuracy_score
from sklearn.cluster import KMeans

RS = 42
u = pd.read_csv("/tmp/social_analysis/social_media_user_behavior.csv")
p = pd.read_csv("/tmp/social_analysis/platform_statistics_2026.csv")

out = []
out.append("# 社交媒体行为分析报告\n")

# --- Q1 ---
out.append("## Q1. 跨表一致性检查\n")
user_mean = u.groupby("primary_platform")["daily_screen_time_minutes"].mean().round(4)
merged = pd.DataFrame({"用户均值": user_mean}).join(
    p.set_index("platform")["avg_daily_time_minutes"].rename("平台表值"), how="inner"
)
merged["差值"] = (merged["用户均值"] - merged["平台表值"]).round(4)
merged = merged.sort_index()
out.append("| 平台 | 用户均值 | 平台表值 | 差值 |")
out.append("|---|---|---|---|")
for plat, row in merged.iterrows():
    out.append(f"| {plat} | {row['用户均值']:.4f} | {row['平台表值']:.4f} | {row['差值']:.4f} |")
r, _ = pearsonr(merged["用户均值"], merged["平台表值"])
out.append(f"\nPearson 相关系数: {r:.4f}\n")
top3 = merged["差值"].abs().sort_values(ascending=False).head(3)
out.append("绝对差最大的 3 个平台:")
for i, (plat, v) in enumerate(top3.items(), 1):
    out.append(f"{i}. {plat}: 绝对差 = {v:.4f}")

# --- Q2 ---
out.append("\n## Q2. 独立性检验\n")
ct = pd.crosstab(u["is_content_creator"], u["has_purchased_via_social"])
out.append("2×2 列联表:\n")
out.append("| | has_purchased_via_social=False | has_purchased_via_social=True |")
out.append("|---|---|---|")
for idx, row in ct.iterrows():
    out.append(f"| is_content_creator={idx} | {int(row[False])} | {int(row[True])} |")
chi2, pval, dof, _ = chi2_contingency(ct.values)
out.append(f"\nchi2 = {chi2:.4f}, dof = {dof}, p_value = {pval:.4f}\n")
out.append(f"结论: 在 α=0.05 水平上，{'拒绝' if pval<0.05 else '无法拒绝'}独立性假设")

# --- Q3 ---
out.append("\n## Q3. 逻辑回归：预测是否通过社交平台购买过\n")
num_cols = ["age","daily_screen_time_minutes","num_platforms_used","engagement_rate_pct",
            "monthly_social_spending_usd","posts_per_week","followers_count"]
bool_cols = ["follows_influencers","is_content_creator","uses_ai_features"]
cat_cols = ["ad_click_frequency","income_bracket","primary_platform"]
cols = num_cols + bool_cols + cat_cols + ["has_purchased_via_social"]
d = u[cols].dropna()
y = d["has_purchased_via_social"].astype(int).values
X_num = d[num_cols].astype(float)
X_bool = d[bool_cols].astype(int)
X_cat = pd.get_dummies(d[cat_cols], drop_first=True).astype(int)
X = pd.concat([X_num, X_bool, X_cat], axis=1)
Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=RS, stratify=y)
sc = StandardScaler()
Xtr_s = Xtr.copy(); Xte_s = Xte.copy()
Xtr_s[num_cols] = sc.fit_transform(Xtr[num_cols])
Xte_s[num_cols] = sc.transform(Xte[num_cols])
clf = LogisticRegression(max_iter=2000, random_state=RS)
clf.fit(Xtr_s, ytr)
train_auc = roc_auc_score(ytr, clf.predict_proba(Xtr_s)[:,1])
test_auc = roc_auc_score(yte, clf.predict_proba(Xte_s)[:,1])
test_acc = accuracy_score(yte, clf.predict(Xte_s))
out.append(f"Train AUC: {train_auc:.4f}")
out.append(f"Test AUC: {test_auc:.4f}")
out.append(f"Test Accuracy: {test_acc:.4f}\n")
coef = pd.Series(clf.coef_[0], index=X.columns)
top5 = coef.reindex(coef.abs().sort_values(ascending=False).head(5).index)
out.append("系数绝对值 Top 5 的特征:\n")
out.append("| 特征 | 系数 |")
out.append("|---|---|")
for f, v in top5.items():
    out.append(f"| {f} | {v:.4f} |")

# --- Q4 ---
out.append("\n## Q4. Simpson's 风险检查\n")
r_all, _ = pearsonr(u["addiction_level_1_to_10"], u["sleep_hours_per_night"])
sub_c = u[u["is_content_creator"]==True]
sub_n = u[u["is_content_creator"]==False]
r_c, _ = pearsonr(sub_c["addiction_level_1_to_10"], sub_c["sleep_hours_per_night"])
r_n, _ = pearsonr(sub_n["addiction_level_1_to_10"], sub_n["sleep_hours_per_night"])
out.append(f"r_all (整体): {r_all:.4f}")
out.append(f"r_creator (创作者): {r_c:.4f}")
out.append(f"r_non_creator (非创作者): {r_n:.4f}\n")
flip = (r_c*r_all<0) or (r_n*r_all<0)
halved = (abs(r_c) < abs(r_all)/2) or (abs(r_n) < abs(r_all)/2)
out.append("符号反转或量级减半以上检查:")
out.append(f"- {'检测到' if (flip or halved) else '未检测到'}符号反转或量级减半以上")

# --- Q5 ---
out.append("\n## Q5. K-Means 行为聚类\n")
feat = ["daily_screen_time_minutes","engagement_rate_pct","posts_per_week","addiction_level_1_to_10"]
X5 = u[feat].values
scaler = StandardScaler()
X5s = scaler.fit_transform(X5)
km = KMeans(n_clusters=4, n_init=10, random_state=RS)
labels = km.fit_predict(X5s)
sizes = pd.Series(labels).value_counts().sort_index()
out.append("每簇规模:\n")
out.append("| 簇 | 用户数 | 占比(%) |")
out.append("|---|---|---|")
n_total = len(u)
for c, n in sizes.items():
    out.append(f"| {c} | {n} | {n/n_total*100:.4f} |")
tmp = u[feat].copy(); tmp["c"] = labels
means = tmp.groupby("c")[feat].mean()
out.append("\n每簇原始特征均值:\n")
out.append("| 簇 | daily_screen_time_minutes | engagement_rate_pct | posts_per_week | addiction_level_1_to_10 |")
out.append("|---|---|---|---|---|")
for i in range(4):
    row = means.loc[i]
    out.append(f"| {i} | {row[feat[0]]:.4f} | {row[feat[1]]:.4f} | {row[feat[2]]:.4f} | {row[feat[3]]:.4f} |")
centers = means.values

def label_for(row):
    screen, eng, posts, addict = row
    if posts > 8: return "重度创作者"
    if addict > 4 and screen > 180: return "高强度沉迷用户"
    if eng > 2.5: return "高参与观众"
    return "低活跃普通用户"
out.append("\n业务标签:")
for i in range(4):
    out.append(f"- 簇 {i}: {label_for(centers[i])}")

# --- Q6 ---
out.append("\n## Q6. 异常参与度用户\n")
big = u[u["followers_count"]>=1000].copy()
big["log_f"] = np.log10(1 + big["followers_count"])
X6 = big[["log_f"]].values
y6 = big["engagement_rate_pct"].values
from sklearn.linear_model import LinearRegression
lr = LinearRegression().fit(X6, y6)
big["predicted"] = lr.predict(X6)
big["residual"] = big["engagement_rate_pct"] - big["predicted"]
top = big.reindex(big["residual"].abs().sort_values(ascending=False).head(5).index)
out.append("残差绝对值 Top 5 用户:\n")
out.append("| user_id | followers_count | engagement_rate_pct | predicted | residual |")
out.append("|---|---|---|---|---|")
for _, r in top.iterrows():
    out.append(f"| {r['user_id']} | {int(r['followers_count'])} | {r['engagement_rate_pct']:.4f} | {r['predicted']:.4f} | {r['residual']:.4f} |")

with open("/tmp/social_analysis/report_v2_claude.md","w") as f:
    f.write("\n".join(out)+"\n")
print("OK")

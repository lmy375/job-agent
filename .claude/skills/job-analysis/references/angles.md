# 角度菜单与脚本骨架

配合 `SKILL.md` 第 3 步用。**九类角度，一次挑 3–5 个**，按用户第 0 步提的问题挑。

下面每一处举的例子都只是**占位**，来自不同行当，刻意不指向任何一个方向——
真正的桶、词、口径一律从当前 profile 的 `resume.md` / `preferences.md` 和用户的话里来。

---

## 一、规模与价格分位

**怎么算**：清洗去重后的条数；`salaryHigh` 的 P25 / 中位 / P75 / P90；
`salaryLow` 的中位；**≥ 用户底线的占比**（底线从 `preferences.md` 或 `[score].salary_floor_wan` 读）。

**怎么读**：
- 「≥底线的占比」是这一角度里唯一直接可行动的数——它等于「这个市场有多少比例的岗位
  一开始就谈不到位」。
- 搜索时设的 `salary_floor` 会**截断左尾**，所以中位数是「门槛以上的中位数」，
  不是这一行的中位数。写结论时带上这句限定。
- 平均数不要报。

## 二、细分方向切分

**怎么算**：按**职位名**分桶（不是 JD 正文——正文里什么都会提一句）。
互斥、先匹配先归属，桶的顺序就是优先级。每桶报：条数、占比、上限中位、≥底线占比。

**怎么读**：
- 桶从**简历与偏好**来：他做过的几段、他说想去的几个方向，各一个桶，
  再加一个「这一行里量最大但他没提的方向」当对照。
- **「其他」超过三成 = 桶切错了**，回去看那三成里是什么。
- 占比大的方向说明「市场在招什么」，价格高的方向说明「市场缺什么」，两者常常不是一个。
- 占比小**且**价格低的方向要专门指出来——尤其当它正好是用户最强的那块。

## 三、需求词频

**怎么算**：一张 `概念名 → 正则` 的表，在职位名 + JD 全文里各搜一次，报提及率。
词表两个来源：① 简历里他会写的词（对照用）；② 先扫一遍 JD 里的高频短语现抽（发现用）。
**不要用内置技能词典**——那是把某一次采集的判断固化下来。

**怎么读**：
- 提及率高 = 这一行的常识，写进简历不加分但不写会扣分。
- 提及率低**且**是他的强项 = 这块能力在这个市场没有买家，是最重要的一类发现。
- 提及率高**且**简历里没有 = 简历该补的词（先确认他真有这个能力，
  **不是让他往简历里加没做过的事**）。
- 同一件事市场用的词和他简历里的词不一样时，改的是**措辞**不是经历。

## 四、供需结构

**怎么算**：猎头挂牌 vs 企业直招的比例；重复挂牌率（`dupes > 1` 的占比、
最多被挂几次）；公司类型 / 行业 / 融资阶段 / 规模分布。

注意 `JobFacts` 里**没有** `jobType`（它不是打分要用的事实），
要按「谁在招」分组得从 `jobs` 表补一列，见下面的骨架。

**怎么读**：
- 猎头占比高 = 岗位在被转手兜售，看到的机会数比真实岗位数虚高；
  企业直招占比高 = 市场更冷静，也更容易直接投。
- 重复挂牌率直接折算：挂牌数 × (1 − 重复率) 才是真实岗位数。
- 公司类型分布回答「谁在招」——甲方、厂商、外包、国企的面试与薪资结构完全不同。

## 五、门槛

**怎么算**：`workYears` / `education` 的分布；JD 正文里明写的年限与学历要求
（结构化字段与正文常常不一致，两个都算）。

**怎么读**：拿用户的实际年限与学历一比，算出「够得着的占比」。
这个数比总条数更接近他的真实池子。

## 六、交叉渗透（A 里提到 B 的比例）

**怎么算**：两个领域各一组词，互相在对方的 JD 里搜，报**双向**比例。
需要两个 profile 时见第八条的同口径要求。

**怎么读**：
- 双向都高 = 两个领域在合流。
- **单向高 = 谁在追谁**：A 的 JD 里六成提到 B、而 B 的 JD 里只有三成提到 A，
  说明是 A 在向 B 靠。对一个横跨两边的候选人，这决定了简历该以哪边为主线。

## 七、溢价在哪一段

**怎么算**：按某个属性（JD 是否提到某类能力、是否某类公司、职位名是否带某个词）
分组，两组都报**中位和 ≥底线占比**，不要只报中位。

**怎么读**：中位一样而 ≥底线占比差十几个点 → 这个属性的作用是
「能不能够到头部那一档」，不是「普遍加薪」。反过来中位差很多而尾部一样，
是整体档位不同。两种情况给用户的建议完全相反。

## 八、跨 profile / 跨时间对照

**怎么算**：见 `SKILL.md` 第 4 步的同口径四条。对照表里**每一行都写上 n**。

**怎么读**：量级（条数比）、价格（分位数差）、结构（猎头占比、门槛占比）分开说。
量级可比不代表结构可比——两边搜的关键词不同时，只谈量级。

## 九、简历 ↔ 市场差距

**怎么算**：把第三条的词频表按「简历里有 / 没有」分两栏，各按提及率排序。

**怎么读**：四个象限，只有两个值得说——
**市场高频 × 简历没有**（要补的，且要先确认他真有）、
**市场低频 × 简历最重**（他最贵的经历没有买家）。
后者往往是整份分析里最该早点告诉他的一句话。

---

## 脚本骨架

写在 scratchpad，不进仓库。事实（关联、去重、薪资解析）一律用仓库的，别自己写：

```python
import re, collections, statistics as st
from job_agent.context import AppContext
from job_agent.core.dataset import load_rows

ctx  = AppContext.create(profile="<名字>", configure_logging=False)
raw  = load_rows(ctx.db, dedupe=False)   # 量口径、算每个关键词准确率用它
ded  = load_rows(ctx.db, dedupe=True)    # 所有比例、分位数用它；dupes 记重复次数

# JobFacts 里没有的列（jobType、companyTags…）从仓储按 jobId 补一张表
from job_agent.core.liepin.enums import JobKind
page = ctx.jobs.find()                                        # 不分页，一次全给
assert page.total == len(page.items), "超过 5000 条会被截断，分批取"
kind = {r.jobId: r.jobType for r in page.items}               # "1" 猎头 / "2" HR，见 JobKind

def text(r):                              # 职位名 + JD 全文
    return " ".join([r.jobName, r.description, r.responsibilities, r.requirements])

# —— 第 1 步：口径。两组词都从用户/偏好来，不是从你来 ——
INCLUDE = re.compile(r'<纳入词>', re.I)          # 这一行的岗位一定会写的词
EXCLUDE = re.compile(r'<同形词陷阱>', re.I)      # 同一字面在别的行当里的意思
def is_target(r):
    if EXCLUDE.search(r.jobName): return False
    return bool(INCLUDE.search(r.jobName))

hit = [r for r in ded if is_target(r)]
print(f"原始 {len(raw)} → 这一行 {len([r for r in raw if is_target(r)])} → 去重 {len(hit)}")

# 每个搜索关键词的准确率——第 6 步要写回 profile.toml 注释
acc = collections.defaultdict(lambda: [0, 0])
for r in raw:
    acc[r.keyword][1] += 1
    acc[r.keyword][0] += is_target(r)
for kw, (ok, tot) in sorted(acc.items(), key=lambda x: -x[1][1]):
    print(f"  {kw:14} {ok:4}/{tot:4}  {ok/tot*100:5.0f}%")

# —— 分位数（角度一）。长尾，别用平均数 ——
def band(rows, label, floor=None):
    h = sorted(r.salaryHigh for r in rows if r.salaryHigh and (floor is None or r.salaryHigh >= floor))
    if len(h) < 10:
        print(f"  {label:20} n={len(h)}（样本太少，只报数不解读）"); return
    q = lambda p: h[int(len(h) * p)]
    print(f"  {label:20} n={len(h):4}  P25 {q(.25):3.0f}  中位 {q(.5):3.0f}  "
          f"P75 {q(.75):3.0f}  P90 {q(.9):3.0f}  ≥底线 {sum(x >= BOTTOM for x in h)/len(h)*100:3.0f}%")

# —— 分桶（角度二）。互斥、先匹配先归属，必须报「其他」 ——
BUCKETS = [("<桶名>", r'<正则>')]   # 桶从简历与偏好来
def bucket(name):
    for n, p in BUCKETS:
        if re.search(p, name, re.I): return n
    return "其他"
```

正则统一用 `re.I`；英文缩写在中文里紧贴汉字时，`\b` 会失效——
用 `(?a:\bxxx\b)` 让括号内只按 ASCII 算边界（同 `[score]` 里的写法）。

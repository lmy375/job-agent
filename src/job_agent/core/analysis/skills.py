"""技能词典：``(展示名, 匹配正则)``。

正则对 JD 全文做 IGNORECASE 搜索，一条 JD 里命中多次只算一次；
同义词（PyTorch / torch、K8s / Kubernetes）合并到同一个展示名。

**词典里不能用过于宽泛的词**——只写「合规」会把命中率虚高到 30%+，
只写「对齐」会命中「对齐业务预期」，``Go`` 直接用 ``\\bgo\\b`` 会命中英文动词。
这几处都在下面限定了上下文，改词典时请保持这个习惯。
"""

from __future__ import annotations

import re

SKILLS: dict[str, list[tuple[str, str]]] = {
    "语言": [
        ("Python", r"\bpython\b"),
        ("C/C++", r"\bc\+\+|\bc/c\+\+|\bcpp\b"),
        # Go 只有两个字母，直接 \bgo\b 会把英文动词 go 也算进来，
        # 因此只在「典型技术栈上下文」里才算命中。
        ("Go", r"\bgolang\b|go语言|\bgo\s*/|/\s*go\b|[、，,]\s*go\s*[、，,]|"
               r"(熟悉|精通|掌握|熟练|会)\s*go\b|\bgo\b\s*(语言|开发|后端|工程)"),
        ("Java", r"\bjava\b(?!script)"),
        ("Rust", r"\brust\b"),
        ("TypeScript/JS", r"\btypescript\b|\bjavascript\b|\bts/js\b|\bnode\.?js\b"),
        ("Solidity", r"\bsolidity\b"),
        ("SQL", r"\bsql\b"),
        ("Shell/Bash", r"\bshell\b|\bbash\b"),
    ],
    "AI 框架与工具": [
        ("PyTorch", r"\bpytorch\b|\btorch\b"),
        ("TensorFlow", r"\btensorflow\b|\btf\b(?=[、，,\s])"),
        ("JAX", r"\bjax\b"),
        ("LangChain", r"\blangchain\b"),
        ("LangGraph", r"\blanggraph\b"),
        ("LlamaIndex", r"\bllama[\s_-]?index\b"),
        ("Dify", r"\bdify\b"),
        ("Coze/扣子", r"\bcoze\b|扣子"),
        ("n8n", r"\bn8n\b"),
        ("AutoGen", r"\bautogen\b"),
        ("CrewAI", r"\bcrew\s?ai\b"),
        ("MCP 协议", r"\bmcp\b|model\s+context\s+protocol"),
        ("HuggingFace", r"hugging\s?face|\bhf\b(?=[、，,\s])|transformers\s+库"),
        ("DeepSpeed", r"\bdeepspeed\b"),
        ("Megatron", r"\bmegatron\b"),
        ("vLLM", r"\bvllm\b"),
        ("SGLang", r"\bsglang\b"),
        ("TensorRT", r"\btensorrt\b|\btrt-?llm\b"),
        ("ONNX", r"\bonnx\b"),
        ("TVM", r"\btvm\b"),
        ("Triton", r"\btriton\b"),
        ("CUDA", r"\bcuda\b"),
        ("Ray", r"\bray\b(?=[、，,\s])|\bray\s*(集群|框架)"),
        ("Kubeflow", r"\bkubeflow\b"),
        ("Ollama", r"\bollama\b"),
    ],
    "AI 技术方向": [
        ("大模型/LLM", r"大模型|\bllm\b|large\s+language\s+model|大语言模型"),
        ("RAG / 知识库", r"\brag\b|检索增强|知识库|向量检索|语义检索"),
        ("Agent / 智能体", r"\bagent\b|智能体|agentic"),
        ("Prompt Engineering", r"prompt|提示词|指令工程"),
        ("微调 SFT/LoRA", r"微调|\bsft\b|\blora\b|\bqlora\b|\bpeft\b|指令调优"),
        ("强化学习 RL/RLHF", r"强化学习|\brl\b(?=[、，,\s])|\brlhf\b|\bppo\b|\bdpo\b|\bgrpo\b"),
        ("预训练 / 后训练", r"预训练|pre-?train|后训练|post-?train|continual\s+pre"),
        ("多模态", r"多模态|multi-?modal|图文|视觉语言|\bvlm\b"),
        ("NLP", r"\bnlp\b|自然语言处理"),
        ("CV / 视觉", r"计算机视觉|\bcv\b(?=[、，,\s])|图像识别|目标检测|\bocr\b"),
        ("语音", r"语音识别|\basr\b|\btts\b|语音合成|声学"),
        ("推荐 / 搜索", r"推荐系统|推荐算法|搜索算法|排序模型|\bctr\b"),
        ("模型量化 / 压缩", r"量化|模型压缩|剪枝|蒸馏|\bptq\b|\bqat\b"),
        ("推理加速", r"推理(加速|优化|性能)|吞吐(优化|提升)|首\s?token|\bkv\s?cache\b"),
        ("向量数据库", r"向量数据库|\bmilvus\b|\bfaiss\b|\bpinecone\b|\bqdrant\b|\bchroma\b|\bpgvector\b"),
        ("评测 / Eval", r"评测|评估体系|\beval(uation)?\s?(集|体系|框架)|benchmark|badcase"),
        ("工作流编排", r"工作流|\bworkflow\b|编排|\bdag\b|流程引擎"),
        ("Context Engineering", r"上下文工程|context\s+engineering|长上下文|长文本"),
        ("A2A / 多智能体", r"多智能体|multi-?agent|\ba2a\b|agent\s+协作"),
        ("论文 / 顶会", r"顶会|neurips|\bicml\b|\biclr\b|\bcvpr\b|\bacl\b|\bmlsys\b|\bkdd\b|"
                        r"\baaai\b|发表论文|一作论文"),
    ],
    "区块链技术": [
        ("EVM / 以太坊", r"\bevm\b|以太坊|ethereum|\beth\b(?=[、，,\s])"),
        ("智能合约", r"智能合约|合约开发|合约审计"),
        ("DeFi", r"\bdefi\b|去中心化金融|\bdex\b|\bamm\b|流动性(挖矿|池)|借贷协议"),
        ("Solana", r"\bsolana\b|\bsol\b(?=[、，,\s])|\banchor\b"),
        ("Bitcoin", r"\bbitcoin\b|比特币|\bbtc\b|\butxo\b|闪电网络|\bordinals?\b"),
        ("Layer2 / Rollup", r"layer\s?2|\bl2\b|rollup|\bzk\b|零知识|zk-?snark|\bstark\b|"
                            r"arbitrum|optimism|\bopstack\b"),
        ("跨链 / 桥", r"跨链|cross-?chain|跨链桥|\bbridge\b"),
        ("钱包 / MPC", r"钱包|\bmpc\b|多签|multi-?sig|\bhd\s?wallet\b|密钥管理|\bkms\b|门限签名"),
        ("交易所 / 撮合", r"交易所|撮合|订单簿|做市|\bcex\b|清结算|合约交易"),
        ("稳定币 / RWA / 支付", r"稳定币|stablecoin|\brwa\b|资产通证化|链上支付|\busdt\b|\busdc\b"),
        ("链上数据 / 索引", r"链上数据|区块链数据|\bsubgraph\b|\bthe\s?graph\b|链上分析|数据索引"),
        # 不能只写「合规」——几乎每份 JD 都会提一句合规，会把命中率虚高到 30%+
        ("合规 / KYC / AML", r"\bkyc\b|\baml\b|反洗钱|金融牌照|监管(合规|要求|报送)|"
                             r"合规(审查|风控|体系|要求)"),
        ("Cosmos / Substrate", r"\bcosmos\b|\bsubstrate\b|\bpolkadot\b|\btendermint\b"),
        ("密码学", r"密码学|椭圆曲线|\becdsa\b|\bschnorr\b|同态加密|\bmpc\b|安全多方计算"),
    ],
    "安全技术": [
        ("漏洞挖掘 / Fuzzing", r"漏洞挖掘|漏洞研究|\bfuzz(ing)?\b|模糊测试|\b0day\b|\bnday\b|\bpoc\b"),
        ("代码审计", r"代码审计|源码审计|白盒|\bsast\b|静态分析"),
        ("渗透测试 / 红队", r"渗透测试|红队|红蓝对抗|\bpentest\b|攻防演练|靶场"),
        ("逆向 / 二进制", r"逆向|反编译|\bida\b|二进制|\bshellcode\b|\bexploit\b|漏洞利用|内核"),
        ("Web 安全", r"web安全|\bxss\b|\bsql注入\b|\bcsrf\b|\bssrf\b|越权|\bowasp\b"),
        ("应用安全 / SDL", r"\bsdl\b|应用安全|安全开发|安全左移|\bdevsecops\b|安全测试"),
        ("云 / 容器安全", r"云安全|容器安全|\bk8s\s?安全|云原生安全|\bcspm\b|\bcwpp\b"),
        ("数据安全 / 隐私", r"数据安全|隐私(计算|保护)|数据脱敏|\bdlp\b|个保法|\bgdpr\b"),
        ("风控 / 反欺诈", r"风控|反欺诈|反作弊|黑产|异常检测|反爬"),
        # 「对齐」在中文 JD 里也常指「对齐业务预期」，必须限定成 AI 语境
        ("AI 安全 / 对齐", r"(AI|模型|大模型).{0,4}安全|对抗样本|越狱|jailbreak|内容安全|"
                           r"(价值观|模型|安全)对齐|alignment|red\s?team.{0,6}(模型|LLM)|"
                           r"prompt\s+injection|提示词注入"),
        ("威胁情报 / 检测响应", r"威胁情报|\bsoc\b|\bsiem\b|\bedr\b|态势感知|应急响应|入侵检测"),
        ("合约安全审计", r"(合约|链上|区块链).{0,4}审计|(合约|链上).{0,4}安全|\bmev\b|经济模型攻击"),
    ],
    "工程与平台": [
        ("Kubernetes/K8s", r"\bk8s\b|kubernetes"),
        ("Docker / 容器", r"\bdocker\b|容器化"),
        ("微服务", r"微服务|micro-?service|\bgrpc\b|服务治理"),
        ("云平台 AWS/阿里云", r"\baws\b|阿里云|腾讯云|华为云|\bgcp\b|\bazure\b|公有云"),
        ("高并发 / 分布式", r"高并发|分布式(系统|架构|存储)|高可用|海量数据|亿级"),
        ("消息队列", r"\bkafka\b|消息队列|\bmq\b|\brabbitmq\b|\bpulsar\b"),
        ("Redis / 缓存", r"\bredis\b|缓存(设计|优化)"),
        ("数据库", r"\bmysql\b|\bpostgres(ql)?\b|\bmongodb\b|\bclickhouse\b|\bhbase\b|\btidb\b"),
        ("CI/CD / DevOps", r"\bci/?cd\b|devops|jenkins|gitlab\s?ci|自动化部署"),
        ("FastAPI/Django", r"\bfastapi\b|\bdjango\b|\bflask\b|\bspring\s?(boot|cloud)\b"),
        ("可观测性", r"可观测|监控告警|prometheus|grafana|链路追踪|\bopentelemetry\b"),
    ],
    "软素质与背景": [
        ("团队管理 / 带人", r"团队管理|带(领)?团队|管理\s?\d+\s?人|tech\s?lead|技术负责人|"
                            r"招聘|培养(团队|下属)|绩效"),
        ("0→1 从零搭建", r"从\s?0\s?到\s?1|0-?1|从零(搭建|开始)|冷启动|开创"),
        ("跨部门协作", r"跨(部门|团队)|协同(产品|业务)|推动落地|向上管理"),
        ("英语 / 海外", r"英语|英文|海外|全球化|\bglobal\b|出海|海外市场"),
        ("开源贡献", r"开源(项目|贡献|社区)|\bgithub\b|\bcommitter\b|\bpr\b\s?贡献"),
        ("学历 985/211", r"985|211|双一流|海外知名|\bqs\b\s?\d|名校"),
        ("大厂经验", r"一线互联网|知名互联网|大厂|头部(公司|企业|厂)|BAT|字节|阿里|腾讯"),
        ("行业理解 / 业务", r"业务理解|行业(理解|经验|知识)|商业(化|价值)|\broi\b|数据驱动"),
        ("技术影响力", r"技术分享|技术(文章|博客)|专利|演讲|布道|技术品牌"),
    ],
}


def skill_hits(text: str) -> dict[str, set[str]]:
    """返回 ``{技能分类: {命中的技能展示名}}``。同一 JD 里同一技能只算一次。"""
    out: dict[str, set[str]] = {}
    for group, items in SKILLS.items():
        hit = {name for name, pattern in items if re.search(pattern, text, re.I)}
        if hit:
            out[group] = hit
    return out

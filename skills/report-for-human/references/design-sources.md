# 设计依据

核对日期：2026-10-14。以下是设计输入，不是每次报告都要检索的材料。

- [GPT-6.1 Sol 官方模型说明](https://developers.openai.com/api/docs/models/gpt-6.1-sol)：适用于复杂编码、计算机使用与专业工作，具备工具调用和结构化输出能力。这里将审查分析交给模型，保留版本、证据与交付约束；不从模型能力推断其结论必然可靠，不硬编码推理档位或基准分数。
- [OpenAI：重新审视技能与提示](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)：强调短描述、渐进披露与减少过度步骤约束。该文专门讨论 Astra；将其作为可检验的技能设计参考，不能声称它是 Sol6.1 的性能证据。
- [OpenAI：仓库评审规则](https://developers.openai.com/blog/custom-code-review-rules-for-codex)：采用有范围、可归因的本地约束，减少无关检查和噪音。
- [Google 工程实践：评审关注点](https://google.github.io/eng-practices/review/reviewer/looking-for.html)：关注设计、行为与代码健康，检查相关上下文及测试是否有效。采用这些后台审查原则，不把每个维度变成报告章节。
- [GitLab：代码评审指南](https://docs.gitlab.com/development/code_review/)：兼容性、可靠性、观测与部署风险用于选择有意义的审查面；不复制其完整组织流程或清单。
- [Anthropic 代码评审代理](https://github.com/anthropics/claude-code/blob/main/plugins/pr-review-toolkit/agents/code-reviewer.md)：借鉴减少误报和可行动发现；不照搬其把严重性与置信度混合评分的做法。
- [OpenAI：系统评估技能](https://developers.openai.com/blog/eval-skills)：用原始任务、实际产物和小规模规则验证改造是否奏效，包含干净反例。可读性需人工/模型独立检查，不能只数标题或测试条数。

本技能的“一张判断页”、三层阅读与长度目标是为当前用户阅读负担作出的设计取舍，并非以上来源声称的通用最优模板。

来源沿革：旧版由 `GitHubxsy/agent-skills` 引入，`amazing-fish/agent-skills` 加入输出位置、规模及 GitHub 固定链接策略。本次保留这些证据边界，重写默认阅读结构；不要求执行环境存在上游锁文件。

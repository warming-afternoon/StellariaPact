# StellariaPact 隐私政策

**最后更新:** 2026-08-06

## 1. 适用范围与运营者

本隐私政策适用于 Discord 应用及机器人 **StellariaPact**（以下简称“本应用”）。本应用目前由个人维护者 **<@954037609313747036>** 运营和维护。

本政策说明本应用在提供社区提案、审核、讨论、投票、异议、公示及相关管理功能时，如何收集、使用、保存、共享和删除数据。

联系方式：

- Discord 服务器及维护讨论帖：https://discord.com/channels/1134557553011998840/1441028880193294366
- 用户可以在上述维护讨论帖中提交隐私问题或数据请求，也可以通过该服务器联系服务器管理员或项目维护者；
- 项目仓库：https://github.com/warming-afternoon/StellariaPact

Discord 独立运营 Discord 平台，并按照 Discord 自己的隐私政策处理数据。本政策仅适用于本应用自身的数据处理活动。

## 2. 我们处理的数据

### 2.1 Discord 标识符和服务器元数据

- Discord 用户 ID；
- 服务器 ID、频道 ID、论坛帖子 ID和消息 ID；
- 与本应用功能有关的身份组 ID；
- 用户显示名称、提及文本及执行操作时提供的成员身份组信息；
- 操作时间、提案状态及其他工作流程元数据。

本应用不要求用户提供 Discord 密码、令牌或其他登录凭据。

### 2.2 提案、审核和公示数据

- 提案标题、提案原因、议案动议、执行方案和执行人；
- 论坛起始消息中的正式提案内容；
- 审核意见、审核人员 ID、审核结果和审核时间；
- 公示标题、内容、截止时间及状态；
- 用户通过模态框、命令、按钮或其他交互主动提交的内容。

### 2.3 投票与异议数据

- 投票用户 ID、投票选项、投票时间和相关投票会话；
- 异议内容、支持记录、处理结果及相关用户 ID；
- 投票资格状态和投票面板所需的数据。

### 2.4 讨论消息内容与参与统计

在服务器管理员明确配置的提案讨论论坛中，本应用会读取消息内容，以判断消息是否属于有效讨论发言。当前判断规则包括消息是否超过规定长度，以及是否仅由表情组成。

对于普通讨论消息：

- 消息内容仅用于即时判断和执行功能；
- 本应用不会有意在数据库中保存每一条普通讨论消息的完整正文；
- 本应用会保存用户 ID、帖子 ID 和计算后的有效发言次数；
- 消息被删除时，本应用可能减少相应计数并更新受影响的投票资格。

作为正式提案、审核意见、公示内容、处罚原因或其他治理记录主动提交的内容，可能会被保存，因为这些内容是相关功能和历史记录的组成部分。

### 2.5 管理与处罚记录

- 被处理用户和管理人员的 Discord 用户 ID；
- 处罚类型、原因、开始和结束时间；
- 相关服务器、帖子和来源消息链接；
- 投票或发言限制状态；
- 解除处罚的记录。

在限制生效期间，本应用可能监听受限制用户在适用提案帖中的新消息，并删除违反该限制的消息。

### 2.6 技术与运行数据

- 应用错误、时间戳、内部任务状态和必要的诊断日志；
- 为防止滥用、保障安全和排查故障所必需的有限技术信息。

本应用不使用 Presence Intent，不收集用户在线、离线、游戏或自定义状态，也不以获取完整服务器成员列表为功能目的。

## 3. 数据用途

我们仅将数据用于以下目的：

- 接收、审核、发布和管理社区提案；
- 创建和维护讨论帖、论坛标签及提案状态；
- 记录投票、统计结果并管理异议；
- 根据有效讨论参与情况判断投票或异议资格；
- 执行服务器管理员设置的提案范围内的限制；
- 发布公示并维护社区治理记录；
- 防止滥用、调查故障并维护本应用的安全和可靠性；
- 遵守适用规则以及 Discord 的开发者条款和政策。

我们不会：

- 出售或出租 Discord API 数据；
- 将数据提供给广告网络或数据经纪商；
- 使用消息内容投放定向广告或建立商业用户画像；
- 使用通过 Discord API 获取的消息内容训练机器学习模型、人工智能模型或大型语言模型；
- 将数据用于与本应用已说明功能无关的目的。

## 4. 数据共享与第三方服务

我们不会出售用户数据。为了运行本应用，我们可能仅在必要范围内向以下服务披露或传输数据：

- **Discord**：用于接收事件、执行命令、发送或编辑消息以及运行机器人功能；
- **托管服务提供商**：用于运行应用、数据库和日志；
- **S3 兼容对象存储提供商**：仅在运营者启用数据库备份功能时，用于存放加密传输的备份文件；
- **安全相关接收方**：在为保护用户、本应用及他人权利与安全确有必要时。

## 5. 数据保存期限

我们遵循数据最小化原则，并仅在实现上述目的所需的期限内保存数据：

- 普通讨论消息正文：用于即时处理，不有意持久保存至应用数据库；
- 运行和错误日志：通常不超过 7 天，但与安全事件或调查有关的记录可在必要期间内保留；
- 数据库备份：不超过 14 天，并通过存储服务的生命周期规则定期删除。

## 6. 用户权利和数据删除

根据适用规则，用户可以请求：

- 了解本应用是否保存了与其关联的数据；
- 获取与其关联的数据副本；
- 更正不准确的数据；
- 删除或匿名化符合条件的数据；
- 在适用情况下限制或反对某些处理；
- 撤回基于同意进行的处理。

请通过我们的 **[Discord 服务器维护讨论帖](https://discord.com/channels/1134557553011998840/1441028880193294366)** 提交申请，或者在该服务器内联系服务器管理员或项目维护者，并提供：

- Discord 用户 ID；
- 申请类型及必要说明。

某些数据可能无法立即删除，例如维护已完成社区决定完整性、防止滥用、处理争议或履行平台规则所必需的记录。在这种情况下，我们会尽可能匿名化或限制相关数据的使用，并说明原因。

## 7. 儿童隐私

本应用不面向未达到其所在司法辖区数字同意最低年龄的儿童。用户必须满足 Discord 使用条款规定的最低年龄要求。我们不会故意收集不符合年龄要求儿童的数据；如果发现此类数据，请联系我们进行删除。

## 8. 自动化决策

本应用会按照服务器配置和预设规则自动计算有效发言次数、投票资格、投票结果以及工作流程状态。这些功能只用于 Discord 社区治理，不用于就业、信贷、住房、保险或其他会对用户产生类似重大影响的决定。

涉及处罚和提案审核的决定由服务器授权人员发起或确认。用户可以联系相关服务器管理员对社区治理决定提出异议。

## 9. 本政策的变更

我们可能因功能、适用规则或 Discord 政策变化而更新本隐私政策。更新后会修改文首的“最后更新”日期。发生重大变化时，我们会通过项目页面、支持服务器或本应用可用的其他适当方式进行通知。

## 10. 联系我们

如对本政策或本应用的数据处理有疑问，或希望行使数据权利，请联系：

- 运营者及个人维护者：<@954037609313747036>
- Discord 服务器及维护讨论帖：https://discord.com/channels/1134557553011998840/1441028880193294366
- 用户也可以在该服务器内联系服务器管理员或项目维护者
- 项目仓库：https://github.com/warming-afternoon/StellariaPact

---

# StellariaPact Privacy Policy

**Last updated:** 2026-08-06

---

## 1. Scope and Operator

This Privacy Policy applies to the Discord application and bot **StellariaPact** (the “Application”). The Application is currently operated and maintained by the individual maintainer **<@954037609313747036>**.

This Policy explains how the Application collects, uses, stores, shares, and deletes data when providing community proposal, review, discussion, voting, objection, announcement, and related moderation features.

Contact information:

- Discord server and maintenance discussion thread: https://discord.com/channels/1134557553011998840/1441028880193294366
- Users may submit privacy questions or data requests in the maintenance discussion thread, or contact a server administrator or the project maintainer within that server;
- Project repository: https://github.com/warming-afternoon/StellariaPact

Discord independently operates the Discord platform and processes data under Discord's own privacy policy. This Policy applies only to processing performed by this Application.

## 2. Data We Process

### 2.1 Discord Identifiers and Server Metadata

- Discord user IDs;
- server IDs, channel IDs, forum thread IDs, and message IDs;
- role IDs relevant to Application functionality;
- display names, mention text, and member role information supplied when an action is performed;
- timestamps, proposal status, and other workflow metadata.

The Application does not ask users for Discord passwords, tokens, or other login credentials.

### 2.2 Proposal, Review, and Announcement Data

- proposal titles, reasons, motions, implementation plans, and executors;
- formal proposal content contained in forum starter messages;
- review comments, reviewer IDs, review outcomes, and review timestamps;
- announcement titles, content, deadlines, and status;
- content intentionally submitted through modals, commands, buttons, or other interactions.

### 2.3 Voting and Objection Data

- voter IDs, selected options, voting timestamps, and associated voting sessions;
- objection content, support records, outcomes, and related user IDs;
- voting eligibility status and information required to maintain voting panels.

### 2.4 Discussion Message Content and Participation Statistics

In proposal discussion forums explicitly configured by server administrators, the Application reads message content to determine whether a message qualifies as meaningful participation. Current rules include whether the message exceeds a specified length and whether it consists only of emoji.

For ordinary discussion messages:

- content is used for immediate classification and functionality;
- the Application does not intentionally store the complete body of every ordinary discussion message in its database;
- the Application stores the user ID, thread ID, and resulting valid participation count;
- when a message is deleted, the Application may reduce the count and update affected voting eligibility.

Content intentionally submitted as a formal proposal, review comment, announcement, moderation reason, or other governance record may be retained because it forms part of the relevant feature and its history.

### 2.5 Moderation and Enforcement Records

- Discord user IDs of affected users and moderators;
- enforcement type, reason, start time, and end time;
- related server, thread, and source message links;
- voting or participation restriction status;
- records of enforcement removal.

While a restriction is active, the Application may monitor new messages from the restricted user in applicable proposal threads and delete messages that violate the restriction.

### 2.6 Technical and Operational Data

- application errors, timestamps, internal task status, and necessary diagnostic logs;
- limited technical information required to prevent abuse, maintain security, and troubleshoot failures.

The Application does not use the Presence Intent and does not collect users' online, offline, game, or custom status. Obtaining complete server member lists is not an intended Application feature.

## 3. How We Use Data

We process data only to:

- receive, review, publish, and manage community proposals;
- create and maintain discussion threads, forum tags, and proposal status;
- record votes, calculate results, and manage objections;
- determine voting or objection eligibility from qualifying discussion participation;
- enforce proposal-specific restrictions configured by server administrators;
- publish announcements and maintain community governance records;
- prevent abuse, investigate failures, and maintain the security and reliability of the Application;
- comply with applicable rules and Discord's developer terms and policies.

We do not:

- sell or rent Discord API data;
- disclose data to advertising networks or data brokers;
- use message content for targeted advertising or commercial user profiling;
- use message content obtained through Discord APIs to train machine-learning models, artificial-intelligence models, or large language models;
- use data for purposes unrelated to the Application's stated functionality.

## 4. Data Sharing and Third-Party Services

We do not sell user data. To operate the Application, we may disclose or transfer data only as necessary to:

- **Discord**, to receive events, process commands, send or edit messages, and operate bot functionality;
- **hosting providers**, to run the Application, database, and logs;
- **S3-compatible object storage providers**, only when database backups are enabled by the operator, to store backup files transmitted over secure connections;
- **security-related recipients**, where reasonably necessary to protect users, the Application, or the rights and safety of others.

## 5. Data Retention

We follow data-minimization principles and retain data only for as long as necessary for the purposes described above:

- ordinary discussion message bodies: used for immediate processing and not intentionally persisted in the Application database;
- operational and error logs: generally retained for no longer than 7 days, except records connected to a security incident or investigation may be retained as necessary;
- database backups: retained for no longer than 14 days and deleted through storage-provider lifecycle rules.

## 6. User Rights and Data Deletion

Under applicable rules, users may request to:

- learn whether the Application stores data associated with them;
- obtain a copy of associated data;
- correct inaccurate data;
- delete or anonymize eligible data;
- restrict or object to certain processing where applicable;
- withdraw consent where processing is based on consent.

Submit requests through our **[Discord server maintenance discussion thread](https://discord.com/channels/1134557553011998840/1441028880193294366)**, or contact a server administrator or the project maintainer within that server. Please include:

- the Discord user ID;
- the request type and necessary details.

Some data may not be immediately deletable when it is necessary to preserve the integrity of completed community decisions, prevent abuse, handle disputes, or comply with platform rules. In such cases, we will anonymize or restrict the data where reasonably possible and explain the reason.

## 7. Children's Privacy

The Application is not directed to children below the minimum age of digital consent in their jurisdiction. Users must meet the minimum age required by Discord's Terms of Service. We do not knowingly collect data from children who do not meet that requirement. Contact us if such data should be deleted.

## 8. Automated Processing

The Application automatically calculates qualifying participation counts, voting eligibility, voting results, and workflow status according to server configuration and predefined rules. These features are used only for Discord community governance and are not used for employment, credit, housing, insurance, or other decisions that produce comparable significant effects.

Moderation and proposal-review decisions are initiated or confirmed by authorized server personnel. Users may contact the relevant server administrators to dispute a community-governance decision.

## 9. Changes to This Policy

We may update this Privacy Policy in response to changes in functionality, applicable rules, or Discord policies. We will update the “Last updated” date at the beginning of this document. For material changes, we will provide notice through the project page, support server, or another appropriate method available through the Application.

## 10. Contact Us

For questions about this Policy or the Application's data processing, or to exercise data rights, contact:

- Operator and individual maintainer: <@954037609313747036>
- Discord server and maintenance discussion thread: https://discord.com/channels/1134557553011998840/1441028880193294366
- Users may also contact a server administrator or the project maintainer within that server
- Project repository: https://github.com/warming-afternoon/StellariaPact

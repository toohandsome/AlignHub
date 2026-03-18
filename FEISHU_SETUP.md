# 飞书接入联调清单（第三版）

本文对应当前项目的 **第三版飞书集成**：

- 一个 Host Bot 负责统一接收群消息
- 每个 Agent 可以绑定一个独立的飞书机器人身份
- 一个飞书群绑定一个系统 `ChatSession`
- 支持新群首次收到命令时自动创建并绑定会话
- 自动建会话时，优先按“群内真实存在的 Agent Bot”识别参与 Agent
- 群里发命令触发多 Agent 讨论
- 单独点名某个 Agent 做问答

---

## 1. 当前代码能力

当前后端已提供以下接口：

- `GET /api/v1/integrations/feishu/config`
- `GET /api/v1/integrations/feishu/agent-bots`
- `PUT /api/v1/integrations/feishu/config`
- `POST /api/v1/integrations/feishu/test-send`
- `POST /api/v1/integrations/feishu/diagnose-chat`
- `POST /api/v1/integrations/feishu/events`

前端入口：

- `/extensions/feishu`
- `/extensions/feishu/bots`
- `/sessions`

---

## 2. 飞书开放平台需要做什么

### 2.1 创建企业自建应用

在飞书开放平台创建一个 **企业自建应用**，并添加 **机器人能力**。

参考：

- 飞书机器人能力说明（飞书官网内容页）：  
  https://www.feishu.cn/content/7298446935354226690
- 添加机器人能力与发布说明（飞书官网内容页）：  
  https://www.feishu.cn/content/425524486655

---

### 2.2 配置应用凭证

你需要拿到：

- `App ID`
- `App Secret`
- `Verification Token`

然后到本项目页面 `/extensions/feishu` 中保存。

---

### 2.3 开启事件订阅

当前代码使用 **“将事件发送至开发者服务器”** 的方式接收消息事件。

事件回调地址配置为：

`POST /api/v1/integrations/feishu/events`

如果你的后端公网地址是：

`https://your-domain.com`

那么飞书后台里应填写：

`https://your-domain.com/api/v1/integrations/feishu/events`

URL 校验 / challenge 机制参考官方文档：

- https://open.feishu.cn/document/server-docs/event-subscription-guide/request-url-configuration-case

> 当前代码只支持 **明文事件**，不要开启 Encrypt Key。

---

### 2.4 订阅消息事件

需要订阅的事件：

- `im.message.receive_v1`

官方文档：

- https://open.feishu.cn/document/server-docs/im-v1/message/events/receive

---

## 3. 建议勾选的权限

基于当前第三版功能，至少需要保证应用具备“收消息 + 发消息 + 群成员识别”能力。

我建议你在飞书后台优先检查这些权限：

- **接收群聊中@机器人消息事件**
- **读取用户发给机器人的单聊消息**
- **以应用的身份发消息**

这几个中文权限名称可参考飞书官网内容页中的机器人接入示例：

- https://www.feishu.cn/content/7291630239830310914

另外，代码当前直接调用了以下官方 API：

- 获取 `tenant_access_token`  
  https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal
- 发送消息  
  https://open.feishu.cn/document/server-docs/im-v1/message/create
- 判断当前身份是否在群中  
  https://open.feishu.cn/document/server-docs/group/chat-members/is-in-chat

因此，如果你在控制台里看到的权限名是更偏 API scope 的写法，也请确保与：

- 接收消息事件
- 发送消息

这两类能力一致。

> 说明：飞书控制台里权限名称有时显示为中文说明，有时显示为 scope 名；这里按当前官方文档与控制台常见命名做了对应。

---

## 4. 应用发布

飞书应用配置完权限和事件后，通常还需要：

1. 创建版本
2. 提交发布
3. 等管理员审批 / 发布完成

未发布或权限未生效时，常见现象是：

- 收不到事件
- 发消息报权限不足
- 机器人无法在群里正常响应

参考：

- https://www.feishu.cn/content/425524486655

---

## 5. 项目侧配置步骤

### 5.1 配飞书应用

打开：

- `/extensions/feishu`

填写：

- `App ID`
- `App Secret`
- `Verification Token`
- 可选：`机器人显示名`

保存后可用“测试发消息”向指定 `chat_id` 发一条测试文本。

---

### 5.1.1 配置 Agent Bot

打开：

- `/extensions/feishu/bots`

为每个需要参与讨论的 Agent 填写：

- `App ID`
- `App Secret`
- `Verification Token`
- `机器人显示名`
- `启用该 Agent Bot`
- `允许该 Agent Bot 直连接收飞书事件`（按需开启）

保存后可以：

- 用“按 Agent 身份测试发消息”验证该机器人能否发消息
- 用“诊断 chat_id”检查某个飞书群里，哪些 Agent Bot 被飞书判定为“在群内”

---

### 5.2 绑定会话与群

打开：

- `/sessions`

在某个会话里填写：

- `feishu_chat_id`
- 勾选 `启用飞书群聊接入`

这一步完成后，该飞书群消息会路由到对应会话。

> 第三版补充：现在新群首次收到命令时，后端会优先自动建会话。  
> 自动识别规则不是只看 @ 文本，而是优先按“群里真实存在的 Agent Bot”做匹配。  
> 注意：飞书官方的“获取群成员列表”接口**不会返回机器人**，所以代码实际采用的是：
> `GET /im/v1/chats/:chat_id/members/is_in_chat`
> 用每个 Agent Bot 自己的身份逐个探测“它是否真的在这个群里”。
> 自动创建的会话默认 `max_rounds = 10`。

---

## 6. 群内可用命令

### 启动讨论

```text
#start 请讨论多 Agent 协作平台如何接入飞书
```

或：

```text
开始讨论：请讨论多 Agent 协作平台如何接入飞书
```

效果：

- 更新当前会话 `topic`
- 启动一个新的 `Run`
- 如果当前群尚未绑定会话，会先自动创建会话
- 讨论过程中的 Agent 发言会自动回推到群里

---

### 单独询问某个 Agent

```text
#ask 架构师: 这个方案最大风险是什么？
```

或：

```text
@架构师 这个方案最大风险是什么？
```

效果：

- 仅调用该 Agent
- 直接返回单条回答
- 不启动完整多 Agent 讨论

---

### 查看帮助

```text
#help
```

或：

```text
帮助
```

---

## 7. 联调建议顺序

建议按下面顺序联调：

1. 后端启动成功
2. 前端启动成功
3. `/extensions/feishu` 保存配置
4. `/extensions/feishu/bots` 配好各 Agent Bot
5. 用测试发消息验证 Host Bot / Agent Bot 都能向群里发消息
6. 飞书后台完成事件订阅 URL 校验
7. 在 `/extensions/feishu/bots` 中用 `chat_id` 诊断，确认目标 Agent Bot 被识别为“在群内”
8. 在群里发 `#help`
9. 再发 `#start xxx`
10. 再测试 `#ask Agent名称: 问题`

---

## 8. 常见问题

### 8.1 收不到回调

优先检查：

- 回调地址是否可公网访问
- 是否已完成 URL challenge 校验
- 是否订阅了 `im.message.receive_v1`
- 是否已发布应用
- 是否关闭了 Encrypt Key

---

### 8.2 能收消息但发不出去

优先检查：

- 是否具备“以应用的身份发消息”
- 机器人是否已在目标群中
- `chat_id` 是否正确

---

### 8.3 群里发了话但系统没触发

优先检查：

- 该群对应的 `feishu_chat_id` 是否已配置到某个会话
- 该会话 `feishu_enabled` 是否开启
- 若还未手工绑定会话，是否已把相关 Agent Bot 拉进群
- 是否使用了当前版本支持的命令格式

---

### 8.4 chat_id 诊断显示“不在群内”

优先检查：

- 该 Agent Bot 是否真的被拉进了目标群
- 机器人名称是否同名但绑定了错误应用
- `/extensions/feishu/bots` 中的 `app_id / app_secret / verification_token` 是否与飞书后台一致
- 该飞书应用是否已发布生效
- 群和应用是否处于同一租户

---

## 9. 第二版边界

当前版本 **还不支持**：

- 飞书事件加密
- 富文本 / 卡片消息交互
- 自动创建群并自动拉机器人

其中“每个 Agent 一个独立飞书机器人身份”已经在第二版实现：

- Host Bot 负责统一接收群事件
- Agent Bot 负责按 Agent 身份发消息
- 也可选地为 Agent Bot 单独开启 `receive_enabled`

# 全局密码输入框可见性切换优化实施计划

为了解决用户在输入密码（包括设备凭据、特权口令、MFA 安全码等）时无法直观确认输入是否正确的问题，我们将对项目中所有目前尚未支持可见性切换的密码输入框进行重构，增加“眼睛”图标切换按钮（利用 `lucide-react` 中的 `Eye` 和 `EyeOff` 图标），实现明文与密文的安全切换。

## 用户审查要求

> [!IMPORTANT]
> 1. 本实施计划已根据最新归档规范使用中文命名，并保存在 `docs/plans/` 目录下。
> 2. 对现有密码输入组件和输入框进行升级，保证在所有密码输入场景（CMDB 凭据管理、特权操作登录、关闭 MFA 验证等）下均能进行明密文切换。
> 3. 前端交互保持精美流畅，切换按钮完美居中对齐，不影响原有输入样式。

## 拟作出的变更

### 1. CMDB 凭据管理页面表单重构

#### [修改] [CmdbManagementTab.tsx](file:///e:/data/netsops/src/pages/CmdbManagementTab.tsx)
* 从 `lucide-react` 导入 `Eye` 和 `EyeOff` 图标。
* 定义 `visiblePasswordFields` 状态（以 Field Key 为键的 Record 状态），支持多个密码框（如登录密码、特权密码、SNMP 共同体等）并行独立控制可见性。
* 重构表单输入循环（lines 599-607）：当 `fd.type === 'password'` 时，使用包裹在 `relative` 容器中的 input，并在右侧加入切换眼睛按钮，动态改变 `type={isVisible ? 'text' : 'password'}`。

### 2. 操作工作台终端接入双因子登录框重构

#### [修改] [AccessCenterTab.tsx](file:///e:/data/netsops/src/pages/AccessCenterTab.tsx)
* 从 `lucide-react` 导入 `Eye` 和 `EyeOff` 图标。
* 定义 `showFixedPassword` 状态，控制 6 位 PIN 固定口令的明暗切换。
* 重构固定码输入框区域（lines 580-593），在 input 框右侧加入绝对定位的眼睛图标按钮。

### 3. 用户个人中心二次认证关闭验证框重构

#### [修改] [ProfileModal.tsx](file:///e:/data/netsops/src/components/ProfileModal.tsx)
* 定义 `showDisablePassword` 状态，控制关闭二次认证时密码确认框的可见性。
* 定义 `showDingtalkSecret` 状态，控制钉钉告警渠道 Secret 密钥输入框的可见性。
* 重构上述两个输入域，在其外层嵌套 `relative` 容器并增加明暗切换眼睛图标。

## 验证计划

### 手动功能与界面验证
1. **CMDB 凭据管理验证**：
   * 打开 **CMDB基础数据 -> 凭据中心**，点击编辑任意 SSH 密码凭据，确认在“密码”、“Enable 密码”、“SNMP Community”输入框右侧均出现小眼睛图标。
   * 点击小眼睛图标，确认密码字符在“••••••”和实际明文密码之间流畅切换。
2. **终端双因子接入验证**：
   * 前往 **操作工作台**，点击网络设备登录，在要求输入“个人身份固定码 (6位 PIN)”处，点击小眼睛，确认能查看明文 PIN 码。
3. **MFA 关闭确认验证**：
   * 点击右上角头像进入个人中心，在“MFA 双因子二次身份认证”栏目下尝试关闭，确认在输入登录密码确认时，密码输入框右侧拥有小眼睛切换功能。
4. **编译与类型安全测试**：
   * 运行 `npm run build` 验证所有导入、TypeScript 类型、Lucide 图标使用无编译期阻碍。

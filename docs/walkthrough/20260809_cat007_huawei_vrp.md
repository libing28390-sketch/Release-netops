# CAT-007 Huawei VRP Walkthrough

## 层级路径

```text
huawei
└── vrp
    ├── vrp5 → V200 → V200R001C00 (draft)
    └── vrp8 → V300 → V300R024C10SPC500 / V300R023C00SPC500 (draft)
```

## 核心验证

- 原始版本字符串保留，normalized/version sort key 可确定性复现。
- VRP5/VRP8、V200/V300 和产品/driver 字段正交。
- `VRP`、train-only、V600、未知/错误版本均不会猜测平台或 driver。
- CAT-001 Huawei source boundary、DB-007 contract、V1 compatibility 和 no-DDL rollback 均通过。

# CAT-008 Cisco IOS / IOS XE / NX-OS / IOS XR Boundary

## Decision

CAT-008 defines four separate Cisco OS families and an explicit C9300 relation:

```text
cisco
├── ios       ── C9300: forbidden
├── ios_xe    ── C9300: supported (17.9.x / 17.18.x)
├── nx_os     ── C9300: forbidden
└── ios_xr    ── C9300: forbidden
```

IOS-XE uses the current canonical system platform profile `cisco_ios` through a reviewed mapping; `cisco_iosxe` and `cisco_xe` are aliases only. No OS string, version or model prefix may silently choose a driver.

## Resolution behavior

- C9300 without an explicit OS family is a series candidate and requires clarification.
- C9300 + IOS-XE is eligible only inside the reviewed 17.9.x/17.18.x scope.
- C9300 + classic IOS, NX-OS or IOS XR is rejected as an incompatible OS relation.
- Unknown or malformed OS/version values preserve the original V1 value and return UNKNOWN/review.
- Product, OS/software and platform/driver remain orthogonal catalog facts.

## Compatibility and rollback

The boundary leaves V1 `cisco_ios`/version fields untouched and adds no production DDL. Disable the CAT-008 applicability resolver to restore the V1 explicit-platform guard.

Final Conclusion: PASS

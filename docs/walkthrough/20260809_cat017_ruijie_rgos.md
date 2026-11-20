# CAT-017 Ruijie RGOS Walkthrough

1. Open the read-only Product Catalog as a reviewed-seed viewer and filter `Vendor = Ruijie`; the three RG-S6220 model samples appear as draft rows.
2. Filter `Software Version = RGOS 11.0(5)B9P59`; only the three Ruijie rows match. `RGOS 11.0(5)B3P2` is the explicit compatibility version and `RGOS 11.0(5)B9P27` remains a reviewed candidate.
3. Inspect a row's advisory mapping: catalog/device/TextFSM identity is `ruijie_rgos`, Netmiko uses `ruijie_os`, and write authority remains false.
4. Try a partial model (`RG-S6220`), unknown model, malformed version, or unknown version. The resolver contract returns candidates/`UNKNOWN` and requires clarification; it never guesses a vendor or driver.
5. Review the source status. Ruijie evidence is pinned to exact `www.ruijie.com.cn` HTTPS paths but remains pending the additive CAT-001 allowlist review, so no collection request is sent.

/** Required identifiers for new asset entry; collected hardware identity stays optional. */
export const getMissingAssetRequiredFields = (asset: { asset_tag?: unknown; management_ip?: unknown }): Array<'asset_tag' | 'management_ip'> => (
  (['asset_tag', 'management_ip'] as const).filter((field) => !String(asset[field] ?? '').trim())
);

export const assetRequiredFieldLabel = (field: 'asset_tag' | 'management_ip', language: string): string => (
  field === 'asset_tag' ? (language === 'zh' ? '资产编号' : 'Asset Tag')
    : (language === 'zh' ? '管理 IP' : 'Management IP')
);

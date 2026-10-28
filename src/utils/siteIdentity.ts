export const isReservedSystemSite = (site: any): boolean => {
  const id = String(site?.id ?? site ?? '').trim().toLowerCase();
  const code = String(site?.site_code ?? '').trim().toLowerCase();
  return id === 'site-default' || code === 'default_site';
};

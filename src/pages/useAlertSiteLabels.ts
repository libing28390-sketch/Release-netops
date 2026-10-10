import { useEffect, useState } from 'react';
import { listSites } from '../api/cmdb';
import { buildAlertSiteLabels, type AlertSiteLabels } from './alertTableExport';

export function useAlertSiteLabels(): AlertSiteLabels {
  const [siteLabels, setSiteLabels] = useState<AlertSiteLabels>(() => new Map());

  useEffect(() => {
    let active = true;
    listSites()
      .then((sites) => {
        if (active) setSiteLabels(buildAlertSiteLabels(sites));
      })
      .catch(() => {
        if (active) setSiteLabels(new Map());
      });
    return () => { active = false; };
  }, []);

  return siteLabels;
}

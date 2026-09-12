export const deleteDevicesByIds = async (deviceIds: string[]) => {
  let successCount = 0;
  let failCount = 0;

  for (const id of deviceIds) {
    try {
      const response = await fetch(`/api/devices/${id}`, { method: 'DELETE' });
      if (response.ok) successCount += 1;
      else failCount += 1;
    } catch {
      failCount += 1;
    }
  }

  return { successCount, failCount };
};

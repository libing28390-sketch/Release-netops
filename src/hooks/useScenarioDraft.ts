import { useCallback } from 'react';
import type { NavigateFunction } from 'react-router-dom';
import { useAutomationStore } from '../store/automationStore';
import { useUiStore } from '../store/uiStore';
import { authHeaders } from '../api/http';

interface UseScenarioDraftArgs {
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  splitLines: (input: string) => string[];
  loadScenarios: () => Promise<void> | void;
  openQuickPlaybookModal: (scenario: any) => void;
  navigate: NavigateFunction;
}

const inferScenarioVariableType = (key: string): 'text' | 'number' => {
  const normalized = key.toLowerCase();
  if (/(id|vlan|asn|metric|count|port|timeout|mtu|weight|preference|cost|bandwidth|delay)$/.test(normalized)) {
    return 'number';
  }
  return 'text';
};

const formatScenarioVariableLabel = (key: string): string =>
  key
    .replace(/[._-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());

export const useScenarioDraft = ({
  showToast,
  splitLines,
  loadScenarios,
  openQuickPlaybookModal,
  navigate,
}: UseScenarioDraftArgs) => {
  const setShowAddScenarioModal = useUiStore((s) => s.setShowAddScenarioModal);
  const newScenarioForm = useAutomationStore((s) => s.newScenarioForm);
  const setNewScenarioForm = useAutomationStore((s) => s.setNewScenarioForm);
  const newScenarioVariables = useAutomationStore((s) => s.newScenarioVariables);
  const setNewScenarioVariables = useAutomationStore((s) => s.setNewScenarioVariables);
  const setScenarioDraftOrigin = useAutomationStore((s) => s.setScenarioDraftOrigin);
  const setIsSavingScenario = useAutomationStore((s) => s.setIsSavingScenario);

  const resetScenarioDraft = useCallback(() => {
    setShowAddScenarioModal(false);
    setNewScenarioForm({
      name: '',
      name_zh: '',
      description: '',
      description_zh: '',
      category: 'Custom',
      icon: '🧩',
      risk: 'medium',
      platform: 'cisco_ios',
      pre_check: '',
      execute: '',
      post_check: '',
      rollback: '',
    });
    setNewScenarioVariables([]);
    setScenarioDraftOrigin({ kind: 'manual', variableKeys: [] });
  }, [setShowAddScenarioModal, setNewScenarioForm, setNewScenarioVariables, setScenarioDraftOrigin]);

  const openManualScenarioDraft = useCallback(() => {
    resetScenarioDraft();
    setShowAddScenarioModal(true);
  }, [resetScenarioDraft, setShowAddScenarioModal]);

  const createScenario = useCallback(async () => {
    if (!newScenarioForm.name.trim()) {
      showToast('Scenario name is required', 'error');
      return;
    }
    if (!newScenarioForm.execute.trim()) {
      showToast('Execute commands cannot be empty', 'error');
      return;
    }

    const platform = newScenarioForm.platform;
    const payload = {
      name: newScenarioForm.name.trim(),
      name_zh: newScenarioForm.name_zh.trim() || newScenarioForm.name.trim(),
      description: newScenarioForm.description.trim(),
      description_zh: newScenarioForm.description_zh.trim() || newScenarioForm.description.trim(),
      category: newScenarioForm.category.trim() || 'Custom',
      icon: newScenarioForm.icon.trim() || '🧩',
      risk: newScenarioForm.risk,
      supported_platforms: [platform],
      default_platform: platform,
      variables: newScenarioVariables,
      platform_phases: {
        [platform]: {
          pre_check: splitLines(newScenarioForm.pre_check),
          execute: splitLines(newScenarioForm.execute),
          post_check: splitLines(newScenarioForm.post_check),
          rollback: splitLines(newScenarioForm.rollback),
        },
      },
    };

    setIsSavingScenario(true);
    try {
      const resp = await fetch('/api/playbooks/scenarios', {
        method: 'POST',
        headers: authHeaders(true),
        body: JSON.stringify(payload),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        showToast(`Error: ${data.detail || resp.statusText}`, 'error');
        return;
      }

      resetScenarioDraft();
      showToast('Custom scenario created', 'success');
      await loadScenarios();
      openQuickPlaybookModal(data);
      navigate('/automation/execute');
    } catch {
      showToast('Connection error', 'error');
    } finally {
      setIsSavingScenario(false);
    }
  }, [
    newScenarioForm,
    newScenarioVariables,
    splitLines,
    setIsSavingScenario,
    resetScenarioDraft,
    showToast,
    loadScenarios,
    openQuickPlaybookModal,
    navigate,
  ]);

  return {
    resetScenarioDraft,
    openManualScenarioDraft,
    createScenario,
    inferScenarioVariableType,
    formatScenarioVariableLabel,
  };
};

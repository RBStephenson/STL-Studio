// Variant-group merge/remove state + handlers for ModelDetail (#678): the
// inline "merge into group" picker, its input and character suggestions, and
// the remove-from-group action. Extracted from ModelDetail.tsx (STUDIO-63 P3)
// — behavior-preserving.

import { useState, useEffect } from "react";
import { api, ModelDetail as ModelDetailType } from "../../../api/client";
import { useToast } from "../../../context/ToastContext";
import { useConfirm } from "../../../context/ConfirmContext";
import { errMsg } from "../../../utils/err";

export interface UseGroupMerge {
  settingGroup: boolean;
  groupInput: string;
  setGroupInput: (value: string) => void;
  savingGroup: boolean;
  groupSuggestions: string[];
  openMergePicker: () => void;
  cancelMerge: () => void;
  mergeIntoGroup: () => Promise<void>;
  removeFromGroup: () => Promise<void>;
}

export function useGroupMerge(
  model: ModelDetailType | null,
  modelId: number | undefined,
  reload: () => void,
): UseGroupMerge {
  const { toast } = useToast();
  const confirm = useConfirm();
  const [settingGroup, setSettingGroup] = useState(false);
  const [groupInput, setGroupInput] = useState("");
  const [savingGroup, setSavingGroup] = useState(false);
  const [groupSuggestions, setGroupSuggestions] = useState<string[]>([]);

  // Close the picker when navigating to a different model.
  useEffect(() => {
    setSettingGroup(false);
  }, [modelId]);

  const openMergePicker = () => {
    setGroupInput("");
    setSettingGroup(true);
    if (model?.creator_id) {
      api.models.characters(model.creator_id).then(setGroupSuggestions).catch(() => {});
    }
  };

  const mergeIntoGroup = async () => {
    if (!model || savingGroup) return;
    const trimmed = groupInput.trim();
    if (!trimmed) return;
    setSavingGroup(true);
    try {
      const { items } = await api.models.variants(model.creator_id!, trimmed);
      const rep = items.find((m) => m.id !== model.id);
      if (!rep?.variant_group_id) {
        toast(`No existing group named "${trimmed}" — pick one from the list.`, "error");
        return;
      }
      const label = rep.variant_group?.label || trimmed;
      await api.models.mergeGroup([model.id], { groupId: rep.variant_group_id, label });
      toast(`Merged into "${label}".`, "success");
      setSettingGroup(false);
      reload();
    } catch (e) {
      toast(errMsg(e) || "Couldn't merge into that group — try again.", "error");
    } finally {
      setSavingGroup(false);
    }
  };

  const removeFromGroup = async () => {
    if (!model || model.variant_group_id == null) return;
    const ok = await confirm({
      title: "Remove from this group?",
      message: "This model will no longer be grouped with its variants. You can merge it into a group again anytime.",
      confirmLabel: "Remove",
    });
    if (!ok) return;
    try {
      await api.models.splitGroup(model.variant_group_id, [model.id]);
      toast("Removed from group.", "success");
      reload();
    } catch (e) {
      toast(errMsg(e) || "Couldn't remove from group — try again.", "error");
    }
  };

  return {
    settingGroup,
    groupInput,
    setGroupInput,
    savingGroup,
    groupSuggestions,
    openMergePicker,
    cancelMerge: () => setSettingGroup(false),
    mergeIntoGroup,
    removeFromGroup,
  };
}

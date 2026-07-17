import React, { useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, Search, Tag, X } from "lucide-react";
import type { TagDefinition } from "../../../types";

interface BatchTagModalProps {
  isOpen: boolean;
  onClose: () => void;
  selectedCount: number;
  allTags: TagDefinition[];
  selectedTagIds: string[];
  setSelectedTagIds: (val: string[]) => void;
  batchTag: () => void;
  language: string;
}

export const BatchTagModal: React.FC<BatchTagModalProps> = ({
  isOpen,
  onClose,
  selectedCount,
  allTags,
  selectedTagIds,
  setSelectedTagIds,
  batchTag,
  language,
}) => {
  const zh = language === "zh";
  const [search, setSearch] = useState("");
  const groupedTags = useMemo(
    () =>
      allTags.filter((tag) => tag.category !== "status").reduce<Record<string, TagDefinition[]>>((groups, tag) => {
        const query = search.trim().toLowerCase();
        if (
          query &&
          ![tag.label, tag.label_zh, tag.value].some((value) =>
            String(value || "")
              .toLowerCase()
              .includes(query),
          )
        )
          return groups;
        const category = tag.category || "other";
        (groups[category] ||= []).push(tag);
        return groups;
      }, {}),
    [allTags, search],
  );

  const toggleTag = (tagId: string) => {
    setSelectedTagIds(
      selectedTagIds.includes(tagId)
        ? selectedTagIds.filter((id) => id !== tagId)
        : [...selectedTagIds, tagId],
    );
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="flex max-h-[min(720px,calc(100vh-48px))] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
            onClick={(event) => event.stopPropagation()}
            initial={{ scale: 0.96, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.96, opacity: 0 }}
          >
            <div className="flex items-start justify-between border-b border-slate-100 px-5 py-4">
              <div>
                <h3 className="flex items-center gap-2 text-base font-bold text-slate-900">
                  <Tag size={16} className="text-cyan-600" />
                  {zh ? "批量编辑标签" : "Edit tags in bulk"}
                </h3>
                <p className="mt-1 text-xs text-slate-400">
                  {selectedCount}{" "}
                  {zh
                    ? "个资产将被更新，可同时选择多个标签"
                    : "assets selected · choose multiple tags at once"}
                </p>
              </div>
              <button
                onClick={onClose}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                <X size={16} />
              </button>
            </div>
            <div className="border-b border-slate-100 px-5 py-3">
              <div className="relative">
                <Search
                  size={14}
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                />
                <input
                  autoFocus
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={
                    zh ? "搜索标签名称或编码…" : "Search tag name or value…"
                  }
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-xs outline-none focus:border-cyan-400 focus:bg-white"
                />
              </div>
              <div className="mt-2 flex items-center justify-between text-[11px] text-slate-500">
                <span>
                  {selectedTagIds.length}{" "}
                  {zh ? "个标签已选择" : "tags selected"}
                </span>
                {selectedTagIds.length > 0 && (
                  <button
                    onClick={() => setSelectedTagIds([])}
                    className="text-rose-500 hover:text-rose-600"
                  >
                    {zh ? "清空选择" : "Clear selection"}
                  </button>
                )}
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
              {Object.keys(groupedTags).length === 0 ? (
                <div className="py-12 text-center text-xs text-slate-400">
                  {zh ? "没有匹配的标签" : "No matching tags"}
                </div>
              ) : (
                Object.entries(groupedTags).map(([category, tags]) => (
                  <div key={category} className="mb-4">
                    <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                      {category}
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {tags.map((tag) => {
                        const selected = selectedTagIds.includes(tag.id);
                        return (
                          <button
                            key={tag.id}
                            onClick={() => toggleTag(tag.id)}
                            className={`flex items-center gap-3 rounded-xl border px-3 py-2 text-left transition-colors ${selected ? "border-cyan-300 bg-cyan-50 text-cyan-800" : "border-slate-100 bg-white text-slate-600 hover:border-cyan-200 hover:bg-slate-50"}`}
                          >
                            <span
                              className="h-2.5 w-2.5 shrink-0 rounded-full"
                              style={{
                                backgroundColor: tag.color || "#94a3b8",
                              }}
                            />
                            <span className="min-w-0 flex-1 truncate text-xs">
                              {zh ? tag.label_zh || tag.label : tag.label}
                              <span className="ml-1 text-[10px] text-slate-400">
                                {tag.value}
                              </span>
                            </span>
                            {selected && (
                              <Check
                                size={14}
                                className="shrink-0 text-cyan-600"
                              />
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))
              )}
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50/70 px-5 py-3">
              <button
                onClick={onClose}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-50"
              >
                {zh ? "取消" : "Cancel"}
              </button>
              <button
                onClick={batchTag}
                disabled={selectedTagIds.length === 0}
                className="rounded-xl bg-cyan-600 px-5 py-2 text-xs font-semibold text-white hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {zh ? "应用标签" : "Apply tags"}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

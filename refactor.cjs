const fs = require('fs');
let content = fs.readFileSync('src/pages/ScheduledJobsTab.tsx', 'utf8');
content = content.replace(/\r\n/g, '\n');

const startTag = '      <AnimatePresence>\n        {modalOpen && (';
const endTag = '        )}\n      </AnimatePresence>\n\n      {/* --- Script Preview Modal --- */}';

const startIndex = content.indexOf(startTag);
const endIndex = content.indexOf(endTag, startIndex);

if (startIndex === -1 || endIndex === -1) {
  console.log('Could not find block');
  console.log('start: ' + startIndex, 'end: ' + endIndex);
  process.exit(1);
}

const block = content.substring(startIndex, endIndex + 26); // include AnimatePresence closing
content = content.substring(0, startIndex) + content.substring(endIndex + 26);

// Now modify the block to use inline styling
let newBlock = block.replace(
  '      <AnimatePresence>\n        {modalOpen && (\n          <motion.div\n            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}\n            className=\"fixed inset-0 z-50 flex items-start justify-center pt-[6vh] px-4 overflow-y-auto\"\n          >\n            {/* Backdrop */}\n            <div className=\"fixed inset-0 bg-black/30 backdrop-blur-sm\" onClick={closeModal} />\n\n            {/* Panel */}\n            <motion.div\n              initial={{ opacity: 0, y: 24, scale: 0.97 }}\n              animate={{ opacity: 1, y: 0, scale: 1 }}\n              exit={{ opacity: 0, y: 16, scale: 0.98 }}\n              transition={{ type: \'spring\', damping: 28, stiffness: 350 }}\n              className={`relative w-full rounded-2xl border border-black/8 bg-white shadow-2xl mb-8 ${form.device_scope === \'ip\' || form.device_scope === \'tag\' ? \'max-w-5xl\' : \'max-w-3xl\'}`}\n              onClick={e => e.stopPropagation()}\n            >\n              {/* Header */}\n              <div className=\"flex items-center justify-between px-6 py-4 border-b border-black/[0.06]\">\n                <h3 className=\"text-base font-bold text-[#164e63] flex items-center gap-2\">\n                  {isEditMode ? <Pencil size={16} className=\"text-cyan-500\" /> : <Plus size={16} className=\"text-cyan-500\" />}\n                  {enablingJobId === editingJob?.id ? (zh ? \'安全启用授权验证\' : \'Enable Scheduled Job (Auth Required)\') : isEditMode ? (zh ? \'编辑定时作业\' : \'Edit Scheduled Job\') : (zh ? \'新建定时作业\' : \'New Scheduled Job\')}\n                </h3>\n                <button onClick={closeModal} className=\"p-1.5 rounded-lg text-black/30 hover:bg-black/5 transition-all\">\n                  <X size={16} />\n                </button>\n              </div>\n\n              {/* Body */}\n              <div className=\"px-6 py-5 space-y-5 max-h-[70vh] overflow-y-auto\">',
  
  '      {/* ── Add/Edit Job Inline Form ── */}\n      <AnimatePresence mode=\"wait\">\n        {showAddJob && (\n          <motion.div\n            key=\"add-form\"\n            initial={{ opacity: 0, y: 20 }}\n            animate={{ opacity: 1, y: 0 }}\n            exit={{ opacity: 0, y: -20 }}\n            className=\"rounded-2xl border border-cyan-200/60 bg-white p-6 space-y-6 shadow-xl relative overflow-hidden mb-6\"\n          >\n            <div className=\"absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-cyan-400 to-blue-500\" />\n            <div className=\"flex items-center justify-between border-b border-black/5 pb-4\">\n              <h3 className=\"text-lg font-bold text-[#164e63] flex items-center gap-2\">\n                <CalendarClock className=\"text-cyan-500\" size={20} />\n                {enablingJobId === editingJob?.id ? (zh ? \'安全启用授权验证\' : \'Enable Scheduled Job (Auth Required)\') : isEditMode ? (zh ? \'编辑定时作业\' : \'Edit Scheduled Job\') : (zh ? \'配置新的定时作业\' : \'Configure New Scheduled Job\')}\n              </h3>\n            </div>\n            <div className=\"grid grid-cols-1 lg:grid-cols-2 gap-8\">'
);

newBlock = newBlock.replace(
  '              {/* Footer */}\n              <div className=\"flex items-center justify-end gap-2 px-6 py-4 border-t border-black/[0.06]\">\n                <button\n                  type=\"button\" onClick={closeModal}\n                  className=\"px-5 py-2 rounded-xl border border-black/[0.08] text-xs font-semibold text-black/50 hover:bg-black/[0.02] transition-all\"\n                >\n                  {zh ? \'取消\' : \'Cancel\'}\n                </button>\n                <button\n                  type=\"button\" onClick={submitForm}\n                  disabled={!form.name.trim() || (!isEditMode && approvalStatus !== \'verified\')}\n                  className=\"px-5 py-2 rounded-xl bg-cyan-600 text-white text-xs font-bold hover:bg-cyan-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-sm\"\n                >\n                  {isEditMode ? (zh ? \'保存修改\' : \'Save Changes\') : (zh ? \'创建定时作业\' : \'Create Scheduled Job\')}\n                </button>\n              </div>\n            </motion.div>\n          </motion.div>\n        )}\n      </AnimatePresence>',
  
  '              <div className=\"lg:col-span-2 pt-4 border-t border-black/5 flex items-center justify-end gap-3\">\n                <button\n                  type=\"button\"\n                  onClick={closeModal}\n                  className=\"px-6 py-2.5 rounded-xl border border-slate-200 text-sm font-bold text-slate-600 hover:bg-slate-50 transition-all\"\n                >\n                  {zh ? \'取消\' : \'Cancel\'}\n                </button>\n                <button\n                  type=\"button\"\n                  onClick={submitForm}\n                  disabled={!form.name.trim() || (!isEditMode && approvalStatus !== \'verified\')}\n                  className=\"px-8 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-bold shadow-md hover:from-cyan-400 hover:to-blue-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed\"\n                >\n                  {isEditMode ? (zh ? \'保存修改\' : \'Save Changes\') : (zh ? \'确认创建\' : \'Confirm Create\')}\n                </button>\n              </div>\n            </div>\n          </motion.div>\n        )}\n      </AnimatePresence>'
);

// Inject right above ═══ 用户自定义作业分栏标题 ═══
const targetInsert = '      {/* ═══ 用户自定义作业分栏标题 ═══ */}';
content = content.replace(targetInsert, newBlock + '\n\n' + targetInsert);

fs.writeFileSync('src/pages/ScheduledJobsTab.tsx', content);
console.log('Success');

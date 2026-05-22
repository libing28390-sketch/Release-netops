const fs = require('fs');
const file = 'd:/tools/netops/src/pages/ScheduledJobsTab.tsx';
let content = fs.readFileSync(file, 'utf8');

const listStartIdx = content.indexOf('{/* ═══ 顶层多维分类导航与搜索栏 ═══ */}');
const formBlockStart = content.indexOf('{/* ── Add/Edit Job Modal Form ── */}');
const listEndMarker = '{/* ═══ 用户自定义作业分栏标题 ═══ */}';
const formBlockEndIdx = content.indexOf(listEndMarker);

if (listStartIdx === -1 || formBlockStart === -1 || formBlockEndIdx === -1) {
  console.log('Could not find markers');
  process.exit(1);
}

const formBlock = content.substring(formBlockStart, formBlockEndIdx);
let newFormBlock = formBlock;

newFormBlock = newFormBlock.replace(/<AnimatePresence>[\s\S]*?\{showAddJob && \([\s\S]*?<motion\.div[\s\S]*?className="fixed inset-0[^>]*>[\s\S]*?<div className="fixed inset-0[^>]*><\/div>[\s\S]*?<motion\.div[\s\S]*?className="relative w-full max-w-5xl rounded-2xl border border-cyan-200\/60 bg-white p-6 shadow-2xl mb-8"[\s\S]*?onClick=\{e => e\.stopPropagation\(\)\}[\s\S]*?>/, 
`{showAddJob ? (
            <motion.div
              key="add-form"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="rounded-2xl border border-cyan-200/60 bg-white p-6 space-y-6 shadow-xl relative overflow-hidden"
            >`);

newFormBlock = newFormBlock.replace(/<button type="button" onClick=\{closeModal\} className="p-1\.5 rounded-lg text-black\/30 hover:bg-black\/5 transition-all">\s*<X size=\{20\} \/>\s*<\/button>/, '');

newFormBlock = newFormBlock.replace(/border-b border-black\/5 pb-4 mb-5/, 'border-b border-black/5 pb-4');

newFormBlock = newFormBlock.replace(/<\/motion\.div>\s*<\/motion\.div>\s*\)\}\s*<\/AnimatePresence>\s*$/s, `</motion.div>\n          ) : (\n            <motion.div\n              key="list-view"\n              initial={{ opacity: 0, y: 20 }}\n              animate={{ opacity: 1, y: 0 }}\n              exit={{ opacity: 0, y: -20 }}\n              className="space-y-4"\n            >\n`);

let finalContent = content.substring(0, formBlockStart) + content.substring(formBlockEndIdx);

const targetInjectionIdx = finalContent.indexOf('{/* ═══ 顶层多维分类导航与搜索栏 ═══ */}');
const beforeInject = finalContent.substring(0, targetInjectionIdx);
const afterInject = finalContent.substring(targetInjectionIdx);

const finalAnimatePresenceEnd = finalContent.lastIndexOf('</div>\n    </div>\n  );\n};');

if (finalAnimatePresenceEnd === -1) {
  console.log('Could not find end of render');
  process.exit(1);
}

const partBeforeEnd = finalContent.substring(targetInjectionIdx, finalAnimatePresenceEnd);
const partAfterEnd = finalContent.substring(finalAnimatePresenceEnd);

finalContent = beforeInject + '<AnimatePresence mode="wait">\n' + newFormBlock + partBeforeEnd + '            </motion.div>\n          )}\n        </AnimatePresence>\n      ' + partAfterEnd;

fs.writeFileSync(file, finalContent);
console.log('Refactoring complete');

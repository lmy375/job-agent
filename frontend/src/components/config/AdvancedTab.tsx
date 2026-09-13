/**
 * 「高级」页：两个配置文件的全文编辑。
 *
 * 前面几页把常改的东西做成了表单，但配置项不止那些——模型接入点、
 * LangSmith、Web 端口、日志、profile 存放位置都只在文件里。与其为每一项
 * 各做一个表单（做完也很少有人点第二次），不如把文件本身交出来：
 * 反正这个页面和那个文件是同一份权限。
 *
 * 两条保证：
 *
 * - **落盘前先校验**。parse 不过、或字段不合法（端口超范围、正则编译不了），
 *   原地拒绝，文件一个字节不动。校验走的就是平时加载配置的那两个模型，
 *   所以「这里保存成功」等价于「下次 CLI 起得来」。
 * - **注释原样**。这里编辑的就是文件本身的文本，前面几页的表单保存时也
 *   只改真正变了的那几行（`config/writer.py` 的按键定点替换）。
 */

import { useEffect, useState } from "react";
import { api, errorMessage } from "../../api";
import type { ConfigFileView, ConfigResponse, ConfigScope } from "../../types";

const SCOPE_META: Record<ConfigScope, { title: string; hint: string }> = {
  global: {
    title: "全局配置",
    hint: "所有 profile 共用的连接与运行配置：猎聘账号与限速、模型接入点与 API Key、Web 服务端口、日志。",
  },
  profile: {
    title: "当前 profile 的配置",
    hint: "仅对当前 profile 生效：搜索条件与关键词、数据文件位置、打分门槛与信号表。",
  },
};

export default function AdvancedTab({
  onSaved,
  onFailed,
}: {
  onSaved: (config: ConfigResponse, notice: string) => void;
  onFailed: (message: string) => void;
}) {
  const [files, setFiles] = useState<ConfigFileView[]>([]);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState("");

  const apply = (list: ConfigFileView[]) => {
    setFiles(list);
    setTexts(Object.fromEntries(list.map((file) => [file.scope, file.text])));
  };

  useEffect(() => {
    api
      .configFiles()
      .then((data) => apply(data.files))
      .catch((e: unknown) => onFailed(errorMessage(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async (scope: ConfigScope) => {
    setSaving(scope);
    try {
      const config = await api.updateConfigFile(scope, texts[scope] ?? "");
      const fresh = await api.configFiles();
      apply(fresh.files);
      onSaved(config, `${SCOPE_META[scope].title}已保存并重新加载。`);
    } catch (e) {
      onFailed(errorMessage(e));
    } finally {
      setSaving("");
    }
  };

  return (
    <>
      <p className="muted">
        保存前会<b>先校验</b>：TOML 语法错误或字段不合法时将拒绝保存，原文件保持不变。
        保存成功后配置立即重新加载，命令行与 <code>job agent</code> 下次运行时使用的
        也是这份配置。
      </p>
      {files.map((file) => (
        <section className="panel" key={file.scope}>
          <h3>
            {SCOPE_META[file.scope].title}
            {!file.exists && <span className="badge warn">文件不存在，保存后自动创建</span>}
          </h3>
          <p className="muted">{SCOPE_META[file.scope].hint}</p>
          <p className="muted mono file-path">{file.path}</p>
          <textarea
            className="mono"
            rows={26}
            spellCheck={false}
            value={texts[file.scope] ?? ""}
            onChange={(e) => setTexts({ ...texts, [file.scope]: e.target.value })}
          />
          <div className="form-actions">
            <button className="btn" disabled={saving !== ""} onClick={() => save(file.scope)}>
              {saving === file.scope ? "保存中…" : "保存"}
            </button>
            <button
              className="link"
              disabled={saving !== ""}
              onClick={() => setTexts({ ...texts, [file.scope]: file.text })}
            >
              放弃修改
            </button>
            <span className="muted">
              共 {(texts[file.scope] ?? "").split("\n").length} 行
              {texts[file.scope] !== file.text && " · 有未保存的修改"}
            </span>
          </div>
        </section>
      ))}
    </>
  );
}

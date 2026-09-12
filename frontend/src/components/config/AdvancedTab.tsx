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
    hint: "管「怎么连」，所有 profile 共用：猎聘账号与限速、模型接入点与 API key、Web 端口、日志。换机器改这里，换求职方向不该动它一个字。",
  },
  profile: {
    title: "当前 profile 的配置",
    hint: "管「找什么」，随人而变：搜索条件与关键词、数据库位置、[score] 打分门槛与信号表。换个人跑就换整个 profile 目录，这个文件跟着走。",
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
        改完按保存会<b>先校验再落盘</b>：TOML 语法不对或字段不合法就原地拒绝，
        文件一个字节不动。保存成功即重新加载，CLI 与 <code>job agent</code>
        下一次跑读到的就是这份。
      </p>
      {files.map((file) => (
        <section className="panel" key={file.scope}>
          <h3>
            {SCOPE_META[file.scope].title}
            {!file.exists && <span className="badge warn">文件还不存在，保存即新建</span>}
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
              放弃改动
            </button>
            <span className="muted">
              {(texts[file.scope] ?? "").split("\n").length} 行
              {texts[file.scope] !== file.text && " · 有未保存的改动"}
            </span>
          </div>
        </section>
      ))}
    </>
  );
}

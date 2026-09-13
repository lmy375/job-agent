import { useState } from "react";
import { api, errorMessage } from "../api";
import type { ScoreRefreshResponse } from "../types";

/**
 * 「重新打分」按钮：调 `/api/scores/refresh`，等价于命令行跑一次 `job score`。
 *
 * 落库的分数会**过期**——改了 `[score]` 或采了新数据，库里存的还是上一次的
 * 分数与全库排名。所以每个会让人看见分数的地方都放一个这个按钮：
 * 职位列表（顶部库存卡报过期就在旁边）、配置页改完打分逻辑之后。
 *
 * 打分是**整表重写**（`rank` 是全库排名，改一条权重会牵动别人的名次），
 * 所以不做「只重算这几条」——那种半新半旧的排名是错的，而且错得看不出来。
 */
export default function RescoreButton({ onDone }: { onDone?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const run = async () => {
    setBusy(true);
    setNote("");
    setError("");
    try {
      const result: ScoreRefreshResponse = await api.refreshScores();
      setNote(
        `已重算 ${result.scored} 条（去重后 ${result.unique} 条，` +
          `未命中硬性要求 ${result.offTrack} 条）`
      );
      onDone?.();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className="rescore">
      <button
        className="btn small"
        disabled={busy}
        onClick={run}
        title="按当前信号表重新计算全部职位的分数与排名"
      >
        {busy ? "打分中…" : "重新打分"}
      </button>
      {note && <span className="rescore-note">{note}</span>}
      {error && <span className="rescore-note err">{error}</span>}
    </span>
  );
}

import React, { useEffect, useRef, useState } from "react";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";

type Game = { id: string; name: string; description: string };
type GameChoice = { id: string; label: string };
type GameState = {
  score: number;
  over: boolean;
  board?: number[][];
  lane?: number;
  holds?: number[];
  deadline?: number;
  prompt?: string;
  choices?: GameChoice[];
  round?: number;
  total_rounds?: number;
  correct?: boolean;
};
type Run = { run_id: string; revision: number; state: GameState; server_time: number };
type Score = { username: string; display_name: string; score: number };
type Scores = { scores: Score[]; has_more: boolean };
type GameTheme = { accent: string; accentText: string; surface: string; raised: string; border: string; text: string; muted: string };

export default function Games({ apiUrl, token, openProfile, theme }: {
  apiUrl: string;
  token: string;
  openProfile: (username: string) => void;
  theme: GameTheme;
}) {
  const [games, setGames] = useState<Game[]>([]);
  const [game, setGame] = useState<Game | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [runReady, setRunReady] = useState(false);
  const [scores, setScores] = useState<Score[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [scoresLoading, setScoresLoading] = useState(false);
  const [error, setError] = useState("");
  const [remaining, setRemaining] = useState(0);
  const [rulesAccepted, setRulesAccepted] = useState<Record<string, boolean>>({});
  const busyRef = useRef(false);
  const scoresBusyRef = useRef(false);
  const currentGame = useRef<string | null>(null);

  async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
    const response = await fetch(`${apiUrl}${path}`, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not load the game.");
    return data as T;
  }
  function showError(value: unknown) {
    setError(value instanceof Error ? value.message : "Something went wrong. Please try again.");
  }
  function instructionsFor(id: string) {
    const instructions: Record<string, string> = {
      "tile-quest": "Slide tiles in one direction to merge matching numbers. Keep merging to grow your score.",
      "summit-steps": "Choose a highlighted hold in your lane or an adjacent lane before the 12-second timer ends.",
      "quick-math": "Solve each math question by choosing one of four answers. You have ten rounds.",
      "word-scramble": "Unscramble the letters and choose the matching word. You have ten rounds.",
      "odd-one-out": "Choose the item that does not belong with the others. You have ten rounds.",
      "number-pattern": "Find the next number in the sequence and choose the correct answer. You have ten rounds.",
      "color-match": "Choose the color named by the prompt. You have ten rounds.",
    };
    return instructions[id] || "Follow the prompt and choose the best answer.";
  }
  useEffect(() => {
    let active = true;
    request<{ games: Game[] }>("/api/games").then(data => {
      if (active) setGames(data.games);
    }).catch(value => { if (active) showError(value); });
    return () => { active = false; currentGame.current = null; };
  }, [apiUrl, token]);
  useEffect(() => {
    if (!run?.state.deadline || run.state.over || game?.id !== "summit-steps") return;
    const initial = Math.max(0, run.state.deadline - run.server_time);
    const started = Date.now();
    const tick = () => setRemaining(Math.max(0, Math.ceil(initial - (Date.now() - started) / 1000)));
    tick();
    const timer = setInterval(tick, 250);
    return () => clearInterval(timer);
  }, [run, game]);

  async function loadScores(id: string, offset = 0) {
    if (scoresBusyRef.current) return;
    scoresBusyRef.current = true;
    setScoresLoading(true);
    try {
      const data = await request<Scores>(`/api/games/${encodeURIComponent(id)}/leaderboard?limit=25&offset=${offset}`);
      if (currentGame.current !== id) return;
      setScores(previous => offset ? [...previous, ...data.scores] : data.scores);
      setHasMore(data.has_more);
    } finally { scoresBusyRef.current = false; setScoresLoading(false); }
  }
  async function chooseGame(selected: Game) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    currentGame.current = selected.id;
    setGame(selected);
    setRulesAccepted(current => ({ ...current, [selected.id]: current[selected.id] ?? false }));
    setRun(null);
    setRunReady(false);
    setScores([]);
    setHasMore(false);
    setError("");
    try {
      const current = await request<{ run: Run | null }>(`/api/games/${encodeURIComponent(selected.id)}/run`);
      if (currentGame.current === selected.id) {
        setRun(current.run);
        setRunReady(true);
      }
      await loadScores(selected.id);
    } catch (value) { showError(value); }
    finally { busyRef.current = false; setBusy(false); }
  }
  async function startGame() {
    if (!game || busyRef.current) return;
    if (!rulesAccepted[game.id]) { setError("Read and acknowledge the game instructions before playing."); return; }
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await request<Run>(`/api/games/${encodeURIComponent(game.id)}/start`, "POST");
      if (currentGame.current === game.id) setRun(result);
    } catch (value) { showError(value); }
    finally { busyRef.current = false; setBusy(false); }
  }
  function confirmStart() {
    if (run && !run.state.over) {
      Alert.alert("Start over?", "Your current game will end, but your best score will be kept.", [
        { text: "Cancel", style: "cancel" },
        { text: "Start over", onPress: () => { void startGame(); } },
      ]);
    } else { void startGame(); }
  }
  async function move(action: string) {
    if (!game || !run || busyRef.current || !rulesAccepted[game.id]) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await request<Run>(`/api/games/${encodeURIComponent(game.id)}/move`, "POST",
        { run_id: run.run_id, revision: run.revision, action });
      if (currentGame.current === game.id) {
        setRun(result);
        void loadScores(game.id).catch(showError);
      }
    } catch (value) { showError(value); }
    finally { busyRef.current = false; setBusy(false); }
  }
  const button = (label: string, onPress: () => void, disabled = false) =>
    <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress}
      style={[styles.button, { backgroundColor: theme.accent, borderColor: theme.accent }, disabled && styles.disabled]}>
      <Text style={[styles.buttonText, { color: theme.accentText }]}>{label}</Text>
    </Pressable>;

  return <View>
    <Text style={[styles.eyebrow, { color: theme.accent }]}>TAKE A LITTLE BREAK</Text>
    <Text style={[styles.title, { color: theme.text }]}>{game ? game.name : "Mini games"}</Text>
    <Text style={[styles.copy, { color: theme.muted }]}>Your best score and username are visible to other members. Games require an internet connection.</Text>
    {error ? <Text accessibilityRole="alert" style={[styles.error, { color: theme.accent }]}>{error}</Text> : null}
    {!game ? games.map(item => <View key={item.id} style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}>
      <Text style={[styles.eyebrow, { color: theme.accent }]}>{item.id === "tile-quest" ? "PUZZLE" : "ADVENTURE"}</Text>
      <Text style={[styles.heading, { color: theme.text }]}>{item.name}</Text><Text style={[styles.copy, { color: theme.muted }]}>{item.description}</Text>
      {button("Open game", () => { void chooseGame(item); })}
    </View>) : <>
      {button("‹ All games", () => { currentGame.current = null; setGame(null); setRun(null); setError(""); }, busy || scoresLoading)}
      <View style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}>
        <Text style={[styles.heading, { color: theme.text }]}>How to play</Text>
        <Text style={[styles.copy, { color: theme.muted }]}>{instructionsFor(game.id)}</Text>
        <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: Boolean(rulesAccepted[game.id]) }}
          onPress={() => setRulesAccepted(current => ({ ...current, [game.id]: !current[game.id] }))}
          style={[styles.rulesCheck, { borderColor: theme.border }]}>
          <Text style={[styles.rulesCheckText, { color: theme.text }]}>{rulesAccepted[game.id] ? "☑" : "□"}  I have read and understand these instructions.</Text>
        </Pressable>
        {run ? <>
          <Text style={[styles.heading, { color: theme.text }]}>Score · {run.state.score}</Text>
          {run.state.round !== undefined && run.state.total_rounds !== undefined
            ? <Text style={[styles.copy, { color: theme.muted }]}>Round {run.state.round} of {run.state.total_rounds}</Text> : null}
          {typeof run.state.correct === "boolean" ? <Text accessibilityLiveRegion="polite"
            style={[styles.copy, { color: run.state.correct ? "#8ce0b1" : theme.muted }]}>{run.state.correct ? "Correct!" : "Not quite. Keep going."}</Text> : null}
          {run.state.prompt && run.state.choices?.length ? <>
            <Text accessibilityRole="header" style={[styles.prompt, { color: theme.text }]}>{run.state.prompt}</Text>
            {!run.state.over ? <View style={styles.choiceList}>{run.state.choices.map(choice =>
              <React.Fragment key={choice.id}>{button(choice.label, () => { void move(choice.id); }, busy || !rulesAccepted[game.id])}</React.Fragment>)}</View> : null}
          </> : null}
          {game.id === "tile-quest" && run.state.board ? <>
            <Text style={[styles.copy, { color: theme.muted }]}>Slide to merge matching tiles.</Text>
            <View style={styles.board}>{run.state.board.flat().map((value, index) =>
              <View key={index} accessible accessibilityLabel={value ? `${value}` : "Empty"}
                style={[styles.tile, { backgroundColor: theme.raised }, value > 0 && { backgroundColor: theme.accent }]}>
                <Text style={[styles.tileText, { color: theme.accentText }]}>{value || ""}</Text>
              </View>)}</View>
            {!run.state.over ? <View style={styles.controls}>
              {(["up", "left", "down", "right"] as const).map(direction =>
                <React.Fragment key={direction}>{button(direction, () => { void move(direction); }, busy || !rulesAccepted[game.id])}</React.Fragment>)}
            </View> : null}
          </> : game.id === "summit-steps" && run.state.holds && run.state.lane !== undefined ? <>
            <Text style={[styles.copy, { color: theme.muted }]}>You are on the {["left", "center", "right"][run.state.lane]} hold. Choose a marked hold in your lane or an adjacent lane within 12 seconds. Missing or running out of time ends your climb.</Text>
            <View style={[styles.cliff, { backgroundColor: theme.raised, borderColor: theme.border }]} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
              <View style={styles.cliffRow}>{[0, 1, 2].map(index => <Text key={index} style={[styles.cliffMark, { color: theme.text }]}>{run.state.holds?.includes(index) ? "◆" : "·"}</Text>)}</View>
              <View style={styles.cliffRow}>{[0, 1, 2].map(index => <Text key={index} style={[styles.cliffMark, { color: theme.text }]}>{run.state.lane === index ? "●" : "·"}</Text>)}</View>
            </View>
            {!run.state.over ? <Text style={[styles.heading, { color: theme.text }]}>{remaining ? `${remaining} seconds left` : "Time is up — choose a hold to finish."}</Text> : null}
            {!run.state.over ? <View style={styles.controls}>{["left", "center", "right"].map((lane, index) =>
              <React.Fragment key={lane}>{button(`${lane}${run.state.holds?.includes(index) ? " · hold" : ""}`, () => { void move(lane); }, busy || !rulesAccepted[game.id])}</React.Fragment>)}</View> : null}
          </> : null}
          {run.state.over ? <Text style={[styles.copy, { color: theme.muted }]}>Game over! Your best score has been saved.</Text> : null}
        </> : null}
        {!runReady && !busy ? <Text style={[styles.copy, { color: theme.muted }]}>Return to all games and reopen this game to retry.</Text> : null}
        {button(run ? "Start over" : "Start playing", confirmStart, busy || !runReady || !rulesAccepted[game.id])}
      </View>
      <View style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.border }]}><Text style={[styles.heading, { color: theme.text }]}>Leaderboard</Text>
        <Text style={[styles.copy, { color: theme.muted }]}>All-time personal bests, highest first.</Text>
        {scores.length ? scores.map((score, index) => <Pressable accessibilityRole="link"
          key={score.username} onPress={() => openProfile(score.username)} style={[styles.scoreRow, { borderColor: theme.border }]}>
          <Text style={[styles.scoreName, { color: theme.text }]}>#{index + 1}  {score.display_name}  @{score.username}</Text>
          <Text style={[styles.scoreValue, { color: theme.accent }]}>{score.score}</Text>
        </Pressable>) : <Text style={[styles.copy, { color: theme.muted }]}>{scoresLoading ? "Loading scores…" : error ? "Scores could not be loaded." : "No scores to show yet."}</Text>}
        {button("Refresh scores", () => { void loadScores(game.id).catch(showError); }, busy || scoresLoading)}
        {hasMore ? button("Load more", () => { void loadScores(game.id, scores.length).catch(showError); }, busy || scoresLoading) : null}
      </View>
    </>}
  </View>;
}

const styles = StyleSheet.create({
  eyebrow: { color: "#c5a9ff", fontSize: 11, letterSpacing: 1.6, fontWeight: "700" },
  title: { color: "#faf8ff", fontSize: 30, fontWeight: "700", marginVertical: 8 },
  heading: { color: "#f8f5ff", fontSize: 20, fontWeight: "700", marginVertical: 6 },
  copy: { color: "#c2bdd6", lineHeight: 21, marginVertical: 6 },
  error: { color: "#ffbac4", marginVertical: 8 },
  card: { backgroundColor: "#19172e", borderColor: "#554675", borderWidth: 1, borderRadius: 18, padding: 16, marginVertical: 8 },
  button: { minHeight: 44, minWidth: 70, justifyContent: "center", alignItems: "center", backgroundColor: "#7254ae", borderRadius: 11, paddingHorizontal: 13, marginVertical: 4 },
  buttonText: { color: "#ffffff", fontWeight: "700" },
  disabled: { opacity: 0.5 },
  controls: { flexDirection: "row", flexWrap: "wrap", gap: 7, marginVertical: 8 },
  board: { flexDirection: "row", flexWrap: "wrap", gap: 4, maxWidth: 340, marginVertical: 10 },
  cliff: { maxWidth: 340, borderRadius: 16, backgroundColor: "#303451", borderWidth: 1, borderColor: "#6c6485", padding: 18, marginVertical: 8 },
  cliffRow: { flexDirection: "row", justifyContent: "space-around", paddingVertical: 12 },
  cliffMark: { color: "#e5dcff", fontSize: 24 },
  tile: { width: "23%", aspectRatio: 1, borderRadius: 9, backgroundColor: "#29233d", alignItems: "center", justifyContent: "center" },
  tileFilled: { backgroundColor: "#61518f" },
  tileText: { color: "#ffffff", fontSize: 19, fontWeight: "800" },
  scoreRow: { flexDirection: "row", justifyContent: "space-between", gap: 8, paddingVertical: 12, borderBottomWidth: 1, borderColor: "#413957" },
  rulesCheck: { minHeight: 48, justifyContent: "center", paddingHorizontal: 10, borderWidth: 1, borderRadius: 10, marginVertical: 8 },
  rulesCheckText: { lineHeight: 21 },
  prompt: { fontSize: 22, fontWeight: "700", lineHeight: 30, marginVertical: 12 },
  choiceList: { gap: 4, marginVertical: 8 },
  scoreName: { color: "#f5f0ff", flexShrink: 1 }, scoreValue: { color: "#f5f0ff", fontWeight: "700" },
});

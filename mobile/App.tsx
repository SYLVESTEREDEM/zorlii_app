import React, { useEffect, useRef, useState } from "react";
import {
  AccessibilityInfo, ActivityIndicator, Alert, Animated, AppState, BackHandler, Easing, findNodeHandle, Image, KeyboardAvoidingView,
  Linking, Modal, Platform, Pressable, ScrollView, Share, StyleSheet, Text, TextInput, useWindowDimensions, View,
} from "react-native";
import * as SecureStore from "expo-secure-store";
import * as ImagePicker from "expo-image-picker";
import * as Clipboard from "expo-clipboard";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import * as Device from "expo-device";
import { VideoView, useVideoPlayer } from "expo-video";
import { SafeAreaProvider, useSafeAreaInsets } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import Games from "./Games";
import { uploadMultipart } from "./upload";
import { isTransientPushServiceUnavailable, pushRegistrationErrorMessage, retryTransientPushOperation } from "./pushRegistration";
import { readThreadPages } from "./threadPagination";

const API_URL = (process.env.EXPO_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});
type ActivityCounts = { posts: number; media: number; replies: number; likes: number; echoes: number; saved: number; messages: number };
type User = { id: number; username: string; email: string; display_name: string; bio: string; avatar_url: string | null; interests: string[]; recommendations_consent: boolean; context_assistance_consent: boolean; terms_accepted: boolean; is_moderator: boolean; theme_color?: string; language?: string; joined_at?: string | null; created_at?: string | null; activity_counts?: ActivityCounts };
type ReportTarget = { target_type: "post" | "user"; target_id: number; label: string };
type ModerationReport = { id: number; target_type: "post" | "user"; post_id: number | null; target_user_id: number | null; target_username: string | null; reporter_username: string; reason: string; details: string; status: string; created_at: string; post_body: string | null };
type PostMedia = { id: number; url: string; media_type: string };
type Author = { id: number; username: string; display_name: string; avatar_url?: string | null };
type Reply = { id: number; post_id?: number; body: string; created_at?: string; reaction_count: number; repost_count: number; reacted: boolean; reposted: boolean; media?: PostMedia[]; quoted_post?: Post | null; quoted_reply?: Reply | null; author: Author };
type Post = { id: number; body: string; created_at: string; reaction_count: number; repost_count: number; reply_count: number; reacted: boolean; reposted: boolean; reposted_reply?: boolean; bookmarked: boolean; reposted_by?: Author | null; quoted_post?: Post | null; quoted_reply?: Reply | null; media?: PostMedia[]; author: Author };

function postsAfterReplyDeletion(posts: Post[], replyId: number): Post[] {
  return posts.filter(post => !(post.reposted_reply && post.quoted_reply?.id === replyId))
    .map(post => post.quoted_reply?.id === replyId ? { ...post, quoted_reply: null } : post);
}

function feedInsertionAnchor(previous: Post[], incoming: Post[], positions: Record<number, number>) {
  const existing = new Set(previous.map(post => post.id));
  const anchorIndex = incoming.findIndex(post => existing.has(post.id));
  if (anchorIndex <= 0 || !incoming.slice(0, anchorIndex).some(post => !existing.has(post.id))) return null;
  const id = incoming[anchorIndex].id;
  return positions[id] === undefined ? null : { id, top: positions[id] };
}
type SocialIconName = "heart" | "repost" | "reply" | "bookmark";
function SocialActionIcon({ name, color, selected }: { name: SocialIconName; color: string; selected: boolean }) {
  if (name === "heart") return <Text accessibilityElementsHidden style={{ color, fontSize: 22, lineHeight: 24, includeFontPadding: false }}>{selected ? "♥" : "♡"}</Text>;
  if (name === "repost") return <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={{ width: 20, height: 20 }}>
    <Text style={{ position: "absolute", top: -3, right: -2, color, fontSize: 15, lineHeight: 18, includeFontPadding: false }}>↻</Text>
    <Text style={{ position: "absolute", bottom: -3, left: -2, color, fontSize: 15, lineHeight: 18, includeFontPadding: false, transform: [{ rotate: "180deg" }] }}>↻</Text>
  </View>;
  if (name === "reply") return <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={{ width: 20, height: 20, alignItems: "center", justifyContent: "center" }}>
    <View style={{ width: 16, height: 13, borderWidth: 1.6, borderColor: color, borderRadius: 4 }} />
    <View style={{ position: "absolute", left: 3, bottom: 1, width: 5, height: 5, borderLeftWidth: 1.6, borderBottomWidth: 1.6, borderColor: color, backgroundColor: "transparent", transform: [{ rotate: "-45deg" }] }} />
  </View>;
  return <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={{ width: 20, height: 20, alignItems: "center", justifyContent: "center" }}>
    <View style={{ position: "absolute", top: 3, left: 5, width: 10, height: 12, backgroundColor: selected ? `${color}22` : "transparent" }} />
    <View style={{ position: "absolute", top: 2, left: 4, width: 12, height: 1.6, backgroundColor: color }} />
    <View style={{ position: "absolute", top: 2, left: 4, width: 1.6, height: 14, backgroundColor: color }} />
    <View style={{ position: "absolute", top: 2, right: 4, width: 1.6, height: 14, backgroundColor: color }} />
    <View style={{ position: "absolute", bottom: 2, left: 4, width: 7, height: 1.6, backgroundColor: color, transform: [{ rotate: "25deg" }] }} />
    <View style={{ position: "absolute", bottom: 2, right: 4, width: 7, height: 1.6, backgroundColor: color, transform: [{ rotate: "-25deg" }] }} />
  </View>;
}
type Conversation = { id: number; created_at?: string; last_message?: string; participants: { id: number; username: string; display_name: string; avatar_url?: string | null }[] };
type DirectMessage = { id: number; body: string; created_at: string; sender_id: number; author: Author };
type PublicProfile = Author & { bio: string; following: boolean; follower_count: number; following_count: number; joined_at?: string | null; created_at?: string | null };
type Member = { id: number; username: string; display_name: string; bio: string; avatar_url?: string | null };
type SocialKind = "followers" | "following";
type NotificationItem = { id: number; kind: "follow" | "reply" | "reaction" | "repost" | "quote" | "message" | "reply_reaction" | "reply_repost" | "mention"; post_id: number | null; reply_id?: number | null; created_at: string; read: boolean; actor: Author };
type QuoteTarget = { type: "post" | "reply"; item: Post | Reply };
type ContentTarget = { type: "post" | "reply"; item: Post | Reply; parentPostId?: number };
type NativeFilePart = { uri: string; name: string; type: string };
type NativeUploadFormData = FormData & { append(name: string, value: string | NativeFilePart): void };
function nativeUploadName(fileName: string | null | undefined, prefix: string, mimeType: string) {
  if (fileName?.trim()) return fileName;
  const knownExtensions: Record<string, string> = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
    "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm",
  };
  const subtype = /^image\/([a-z0-9.+-]+)$/i.exec(mimeType)?.[1]
    || /^video\/([a-z0-9.+-]+)$/i.exec(mimeType)?.[1];
  const extension = knownExtensions[mimeType] || (mimeType === "application/octet-stream" ? "bin" : subtype || "bin");
  return `${prefix}.${extension}`;
}
const DEFAULT_ACCENT = "#a47dff";
const AUTH_PAGE_BACKGROUND_IMAGE = [
  {
    type: "radial-gradient",
    shape: "ellipse",
    size: "farthest-corner",
    position: { top: "0%", left: "50%" },
    colorStops: [
      { color: "#45207835", positions: ["0%"] },
      { color: "transparent", positions: ["44%"] },
    ],
  },
  {
    type: "linear-gradient",
    direction: "160deg",
    colorStops: [
      { color: "#070713", positions: ["0%"] },
      { color: "#0b1020", positions: ["70%"] },
      { color: "#090b18", positions: ["100%"] },
    ],
  },
] as const;
const AUTH_CARD_BACKGROUND_IMAGE = [
  {
    type: "linear-gradient",
    direction: "150deg",
    colorStops: [
      { color: "#17152d", positions: ["0%"] },
      { color: "#111329", positions: ["84%"] },
    ],
  },
] as const;
let activeThemeAccent = DEFAULT_ACCENT;
let activeReduceMotion = true;
function validHexColor(value?: string | null): value is string { return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value); }
function canRegisterPushToken(platform: string, isDevice: boolean) {
  return platform === "android" || (platform === "ios" && isDevice);
}
function colorLuminance(color: string) {
  const [red, green, blue] = color.slice(1).match(/.{2}/g)!.map(part => parseInt(part, 16) / 255)
    .map(channel => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}
function contrastForeground(color: string) { return colorLuminance(color) > 0.179 ? "#11111b" : "#ffffff"; }
function readableAccent(color: string) {
  const raisedSurfaceLuminance = colorLuminance("#5d5d6d");
  return (colorLuminance(color) + 0.05) / (raisedSurfaceLuminance + 0.05) >= 4.5 ? color : "#ffffff";
}
type HslColor = { hue: number; saturation: number; lightness: number };
function hslFromColor(color: string): HslColor {
  const [red, green, blue] = color.slice(1).match(/.{2}/g)!.map(part => parseInt(part, 16) / 255);
  const max = Math.max(red, green, blue), min = Math.min(red, green, blue), delta = max - min;
  const lightness = (max + min) / 2;
  if (!delta) return { hue: 0, saturation: 0, lightness: Math.round(lightness * 100) };
  const hue = max === red ? ((green - blue) / delta) % 6 : max === green ? (blue - red) / delta + 2 : (red - green) / delta + 4;
  const saturation = delta / (1 - Math.abs(2 * lightness - 1));
  return { hue: Math.round((hue * 60 + 360) % 360), saturation: Math.round(saturation * 100), lightness: Math.round(lightness * 100) };
}
function colorFromHsl(hue: number, saturation: number, lightness: number) {
  const normalizedHue = ((hue % 360) + 360) % 360;
  const s = saturation / 100, l = lightness / 100;
  const chroma = (1 - Math.abs(2 * l - 1)) * s;
  const section = normalizedHue / 60, secondary = chroma * (1 - Math.abs(section % 2 - 1)), offset = l - chroma / 2;
  const channels = section < 1 ? [chroma, secondary, 0] : section < 2 ? [secondary, chroma, 0]
    : section < 3 ? [0, chroma, secondary] : section < 4 ? [0, secondary, chroma]
      : section < 5 ? [secondary, 0, chroma] : [chroma, 0, secondary];
  return `#${channels.map(channel => Math.round((channel + offset) * 255).toString(16).padStart(2, "0")).join("")}`;
}
function mixColor(color: string, base: string, amount: number) {
  const foreground = color.slice(1).match(/.{2}/g)!.map(part => parseInt(part, 16));
  const background = base.slice(1).match(/.{2}/g)!.map(part => parseInt(part, 16));
  return `#${foreground.map((channel, index) => Math.round(background[index] + (channel - background[index]) * amount)
    .toString(16).padStart(2, "0")).join("")}`;
}
function SpectrumSlider({ label, value, max, colors, selectedColor, onChange }: {
  label: string; value: number; max: number; colors: string[]; selectedColor: string; onChange: (value: number) => void;
}) {
  const [width, setWidth] = useState(1);
  const selectAt = (x: number) => onChange(Math.max(0, Math.min(max, Math.round(x / width * max))));
  const step = max === 359 ? 5 : 1;
  return <View style={styles.colorControl}>
    <Text style={styles.colorControlLabel}>{label}</Text>
    <View accessibilityRole="adjustable" accessibilityLabel={`${label} value`}
    accessibilityHint="Swipe across the spectrum or adjust the value with accessibility controls."
    accessibilityValue={{ min: 0, max, now: Math.round(value), text: max === 359 ? `${Math.round(value)} degrees` : `${Math.round(value)} percent` }}
    accessibilityActions={[{ name: "increment", label: `Increase ${label.toLowerCase()}` }, { name: "decrement", label: `Decrease ${label.toLowerCase()}` }]}
    onAccessibilityAction={event => onChange(Math.max(0, Math.min(max, Math.round(value) + (event.nativeEvent.actionName === "increment" ? step : -step))))}
    onLayout={event => setWidth(event.nativeEvent.layout.width)}
    onStartShouldSetResponder={() => true} onMoveShouldSetResponder={() => true}
    onResponderGrant={event => selectAt(event.nativeEvent.locationX)}
    onResponderMove={event => selectAt(event.nativeEvent.locationX)}
    style={styles.huePicker}>
    <View pointerEvents="none" style={styles.hueSpectrum}>
      {colors.map((color, index) => <View key={index} style={{ flex: 1, backgroundColor: color }} />)}
      <View style={[styles.hueThumb, { left: `${value / max * 100}%`, borderColor: contrastForeground(selectedColor) }]} />
    </View>
    </View>
  </View>;
}
function HueSpectrumPicker({ value, onChange }: { value: string; onChange: (color: string) => void }) {
  const [hsl, setHsl] = useState<HslColor>(() => hslFromColor(value));
  useEffect(() => setHsl(hslFromColor(value)), [value]);
  const update = (axis: keyof HslColor, nextValue: number) => {
    const next = { ...hsl, [axis]: nextValue };
    setHsl(next);
    onChange(colorFromHsl(next.hue, next.saturation, next.lightness));
  };
  const color = colorFromHsl(hsl.hue, hsl.saturation, hsl.lightness);
  const hues = Array.from({ length: 36 }, (_, index) => colorFromHsl(index * 10, 100, 50));
  const saturations = Array.from({ length: 36 }, (_, index) => colorFromHsl(hsl.hue, Math.round(index / 35 * 100), hsl.lightness));
  const lightnesses = Array.from({ length: 36 }, (_, index) => colorFromHsl(hsl.hue, hsl.saturation, Math.round(index / 35 * 100)));
  return <View>
    <SpectrumSlider label="Hue" value={hsl.hue} max={359} colors={hues} selectedColor={color} onChange={next => update("hue", next)} />
    <SpectrumSlider label="Saturation" value={hsl.saturation} max={100} colors={saturations} selectedColor={color} onChange={next => update("saturation", next)} />
    <SpectrumSlider label="Lightness" value={hsl.lightness} max={100} colors={lightnesses} selectedColor={color} onChange={next => update("lightness", next)} />
  </View>;
}
function formatJoinedDate(value?: string | null, language = "en-US") {
  if (!value) return "";
  const text = value.trim();
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(text) ? `${text}T00:00:00Z`
    : text.includes("T") ? text : text.includes(" ") ? text.replace(" ", "T") : `${text}T00:00:00Z`;
  const date = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : `${normalized}Z`);
  if (Number.isNaN(date.getTime())) return "";
  if (language && language !== "en-US") {
    const labels: Record<string, string> = { "fr-FR": "Membre depuis le", "es-ES": "Se unió el", ar: "انضم في", "hi-IN": "", ur: "شمولیت:" };
    if (!Object.prototype.hasOwnProperty.call(labels, language)) throw new Error(`Unsupported language: ${language}`);
    const formatted = new Intl.DateTimeFormat(language, { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(date);
    return language === "hi-IN" ? `${formatted} को शामिल हुए` : `${labels[language]} ${formatted}`;
  }
  const day = date.getUTCDate();
  const suffix = day % 100 >= 11 && day % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[day % 10] || "th";
  const month = new Intl.DateTimeFormat("en", { month: "long", timeZone: "UTC" }).format(date);
  return `Joined ${day}${suffix} ${month}, ${date.getUTCFullYear()}`;
}

function PostVideo({ uri, token, style = styles.postVideo }: { uri: string; token: string; style?: any }) {
  const player = useVideoPlayer(
    { uri, headers: { Authorization: `Bearer ${token}` } },
    instance => { instance.loop = false; },
  );
  return <VideoView style={style} player={player} nativeControls contentFit="contain" />;
}

function MediaPickerButton({ label, onPress }: { label: string; onPress: () => void }) {
  return <Pressable accessibilityRole="button" accessibilityLabel={label}
    accessibilityHint="Choose photos, videos, or GIFs to attach."
    onPress={() => onPress()} style={({ pressed }) => [styles.mediaPickerButton, { borderColor: readableAccent(activeThemeAccent), backgroundColor: mixColor(activeThemeAccent, "#17132a", 0.22) },
      pressed && (activeReduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
    <Text style={[styles.mediaPickerIcon, { color: readableAccent(activeThemeAccent) }]} accessibilityElementsHidden>+</Text>
  </Pressable>;
}

function passwordPolicyError(password: string) {
  if (password.length < 4 || password.length > 128) return "Use 4–128 characters.";
  if (!/[A-Z]/.test(password)) return "Add at least one uppercase letter.";
  if (!/[a-z]/.test(password)) return "Add at least one lowercase letter.";
  if (!/[0-9]/.test(password)) return "Add at least one number.";
  if (!/[^A-Za-z0-9\s]/.test(password)) return "Add at least one special character.";
  return "";
}

function passwordRequirements(password: string) {
  return [
    { label: "4–128 characters", met: password.length >= 4 && password.length <= 128 },
    { label: "An uppercase letter", met: /[A-Z]/.test(password) },
    { label: "A lowercase letter", met: /[a-z]/.test(password) },
    { label: "A number", met: /[0-9]/.test(password) },
    { label: "A special character", met: /[^A-Za-z0-9\s]/.test(password) },
  ];
}

function activityDescription(kind: NotificationItem["kind"]) {
  const descriptions: Record<NotificationItem["kind"], string> = {
    follow: "started following you.",
    reply: "replied to your post.",
    reaction: "liked your post.",
    repost: "echoed your post.",
    quote: "shared a thought about your post.",
    message: "sent you a message.",
    reply_reaction: "liked your reply.",
    reply_repost: "echoed your reply.",
    mention: "mentioned you.",
  };
  return descriptions[kind] || "shared an update with you.";
}

function mergeMessages(current: DirectMessage[], incoming: DirectMessage[]) {
  const byId = new Map<number, DirectMessage>();
  [...current, ...incoming].forEach(message => byId.set(message.id, message));
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

function mergeProfilePosts(current: Post[], incoming: Post[]) {
  const byId = new Map<number, Post>();
  [...current, ...incoming].forEach(post => byId.set(post.id, post));
  return [...byId.values()].sort((a, b) => b.id - a.id);
}

function parsedDate(value: string) {
  const normalized = value.includes("T") ? value : value.includes(" ") ? value.replace(" ", "T") : `${value}T00:00:00`;
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : `${normalized}Z`);
}

function formatMessageTime(value: string) {
  const date = parsedDate(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function formatConversationDate(value: string) {
  const date = parsedDate(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { dateStyle: "long" });
}

function BrandHalo({ size = 48, showLogo = false, quiet = false }: { size?: number; showLogo?: boolean; quiet?: boolean }) {
  return <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
    style={[styles.brandHaloWrap, quiet && styles.quietBrandHaloWrap, { width: size + 14, height: size + 14, borderRadius: (size + 14) / 2 }]}>
    <View style={[styles.brandHaloRing, quiet && styles.quietBrandHaloRing, { width: size + 8, height: size + 8, borderRadius: (size + 8) / 2, borderColor: readableAccent(activeThemeAccent) }]}>
      <View style={[styles.brandCore, quiet && styles.quietBrandCore, { width: size, height: size, borderRadius: size / 2 }]}>
        {showLogo
          ? <Image source={require("./assets/zorlii-logo.png")} style={[styles.logo, { width: size, height: size, borderRadius: size / 2 }]} resizeMode="contain" />
          : <Text style={[styles.brandMonogram, { fontSize: size * 0.43 }]}>Z</Text>}
      </View>
    </View>
    <View style={[styles.brandPulse, quiet && styles.quietBrandPulse]} />
  </View>;
}

function Avatar({ user, size = 42, onPress }: {
  user?: { display_name?: string; username?: string; avatar_url?: string | null } | null;
  size?: number;
  onPress?: () => void;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const name = user?.display_name || user?.username || "Zorlii member";
  const initials = name.trim().split(/\s+/).slice(0, 2).map(part => part[0] || "").join("").toUpperCase() || "Z";
  useEffect(() => { setImageFailed(false); }, [user?.avatar_url]);
  const contents = <View accessible={!onPress} accessibilityRole={onPress ? undefined : "image"}
    accessibilityLabel={user?.avatar_url && !imageFailed ? `${name} profile photo` : `${initials} initials`}
    style={[styles.avatarHalo, { width: size + 10, height: size + 10, borderRadius: (size + 10) / 2, borderColor: readableAccent(activeThemeAccent) }]}>
    <View style={[styles.avatar, { width: size, height: size, borderRadius: size / 2 }]}>
      {user?.avatar_url && !imageFailed
        ? <Image source={{ uri: `${API_URL}${user.avatar_url}` }} style={styles.avatarImage} onError={() => setImageFailed(true)} />
        : <Text style={styles.avatarInitials}>{initials}</Text>}
    </View>
    <View style={styles.avatarPulse} />
  </View>;
  return onPress
    ? <Pressable accessibilityRole="button" accessibilityLabel={`View ${name}'s profile photo larger`} onPress={onPress}>{contents}</Pressable>
    : contents;
}

function AppContent() {
  const insets = useSafeAreaInsets();
  const { width: windowWidth, height: windowHeight } = useWindowDimensions();
  const menuDrawerWidth = Math.min(windowWidth * 0.86, 360);
  const composerRef = useRef<React.ElementRef<typeof TextInput> | null>(null);
  const composerInputRefs = useRef<Record<string, React.ElementRef<typeof TextInput> | null>>({});
  const pushTokenRef = useRef<string | null>(null);
  const pushRegistrationPromiseRef = useRef<Promise<boolean | "blocked"> | null>(null);
  const pushSessionRef = useRef("");
  const pushSessionGenerationRef = useRef(0);
  const pushRegistrationOwnerRef = useRef("");
  const pushRegistrationGenerationRef = useRef(0);
  const pushPostingRef = useRef(false);
  const pushRetryPendingRef = useRef(false);
  const pushReturnRetryUsedRef = useRef(false);
  const activeConversationIdRef = useRef<number | null>(null);
  const conversationGenerationRef = useRef(0);
  const messagesRef = useRef<DirectMessage[]>([]);
  const messageDraftsRef = useRef<Record<number, string>>({});
  const messageDraftVersionRef = useRef<Record<number, number>>({});
  const messageScrollRef = useRef<React.ElementRef<typeof ScrollView> | null>(null);
  const messageScrollYRef = useRef(0);
  const messagePositionsRef = useRef(new Map<number, number>());
  const messageRestoreOffsetRef = useRef<{ id: number; top: number; offset: number } | null>(null);
  const messageLatestTargetRef = useRef<number | null>(null);
  const profileReturnScreenRef = useRef("feed");
  const publicProfileUsernameRef = useRef("");
  const profileUserRef = useRef<number | null>(null);
  const profileLoadedOlderRef = useRef(false);
  const publicProfileLoadedOlderRef = useRef(false);
  const socialListRequestRef = useRef(0);
  const followLookupRequestRef = useRef<Record<string, number>>({});
  const hashtagRequestRef = useRef(0);
  const mentionRequestRef = useRef(0);
  const searchRequestRef = useRef(0);
  const inboxSearchRequestRef = useRef(0);
  const feedRequestRef = useRef(0);
  const postSubmissionRef = useRef(false);
  const replySubmissionRef = useRef(new Set<number>());
  const threadRequestRef = useRef(0);
  const threadLoadingMoreRef = useRef(false);
  const threadRefreshBusyRef = useRef(false);
  const threadRefreshAgainRef = useRef(false);
  const threadRefreshLatestRef = useRef<() => Promise<void>>(async () => {});
  const threadReturnScreenRef = useRef("feed");
  const threadTargetReplyRef = useRef<number | null>(null);
  const threadTopRef = useRef(0);
  const screenBodyTopRef = useRef(0);
  const feedPollRef = useRef(0);
  const feedScrollRef = useRef<React.ElementRef<typeof ScrollView> | null>(null);
  const feedScrollYRef = useRef(0);
  const feedPostPositionsRef = useRef<Record<number, number>>({});
  const pendingFeedAnchorRef = useRef<{ id: number; top: number; scope: string } | null>(null);
  const contentMenuAnchorsRef = useRef<Record<string, React.ElementRef<typeof Pressable> | null>>({});
  const inputSelectionsRef = useRef<Record<string, { start: number; end: number }>>({});
  const [token, setToken] = useState("");
  const [me, setMe] = useState<User | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(true);
  const [splashVisible, setSplashVisible] = useState(true);
  const splashGlow = useRef(new Animated.Value(0)).current;
  const [visiblePasswords, setVisiblePasswords] = useState<Record<string, boolean>>({});
  const authSubmissionRef = useRef(false);
  const screenOpacity = useRef(new Animated.Value(1)).current;
  const screenOffset = useRef(new Animated.Value(0)).current;
  const menuTranslateX = useRef(new Animated.Value(360)).current;
  const menuScrimOpacity = useRef(new Animated.Value(0)).current;
  const menuClosePendingRef = useRef(false);
  const menuToggleRef = useRef<React.ElementRef<typeof Pressable> | null>(null);
  const menuCloseButtonRef = useRef<React.ElementRef<typeof Pressable> | null>(null);
  const [themeColorDraft, setThemeColorDraft] = useState(DEFAULT_ACCENT);
  const [screen, setScreen] = useState("login");
  const compactAuth = windowHeight <= 700;
  const [loading, setLoading] = useState(false);
  const [feedLoading, setFeedLoading] = useState(false);
  const [error, setError] = useState("");
  const [posts, setPosts] = useState<Post[]>([]);
  const [contentMenu, setContentMenu] = useState<{ type: "post" | "reply"; id: number } | null>(null);
  const [contentMenuPlacement, setContentMenuPlacement] = useState<"above" | "below">("below");
  const [editingContent, setEditingContent] = useState<ContentTarget | null>(null);
  const [editingBody, setEditingBody] = useState("");
  const [postMedia, setPostMedia] = useState<ImagePicker.ImagePickerAsset[]>([]);
  const [replyMediaByPost, setReplyMediaByPost] = useState<Record<number, ImagePicker.ImagePickerAsset[]>>({});
  const [threadPost, setThreadPost] = useState<Post | null>(null);
  const [threadReplies, setThreadReplies] = useState<Reply[]>([]);
  const [threadHasMore, setThreadHasMore] = useState(false);
  const [threadNextAfterId, setThreadNextAfterId] = useState<number | null>(null);
  const [threadLoading, setThreadLoading] = useState(false);
  const [threadLoadingMore, setThreadLoadingMore] = useState(false);
  const [threadRefreshing, setThreadRefreshing] = useState(false);
  const [threadError, setThreadError] = useState("");
  const [quoteTarget, setQuoteTarget] = useState<QuoteTarget | null>(null);
  const [echoTarget, setEchoTarget] = useState<QuoteTarget | null>(null);
  const [focusedEchoOption, setFocusedEchoOption] = useState<"echo" | "thought" | "cancel" | null>(null);
  const [profilePosts, setProfilePosts] = useState<Post[]>([]);
  const [profileHasMore, setProfileHasMore] = useState(false);
  const [loadingProfileOlder, setLoadingProfileOlder] = useState(false);
  const [activityCounts, setActivityCounts] = useState<ActivityCounts | null>(null);
  const [replies, setReplies] = useState<Record<number, any[]>>({});
  const [scope, setScope] = useState("all");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [socialList, setSocialList] = useState<{ username: string; kind: SocialKind; users: Member[]; count: number } | null>(null);
  const [socialListLoading, setSocialListLoading] = useState(false);
  const [hashtag, setHashtag] = useState("");
  const [hashtagPosts, setHashtagPosts] = useState<Post[]>([]);
  const [hashtagHasMore, setHashtagHasMore] = useState(false);
  const [hashtagLoading, setHashtagLoading] = useState(false);
  const [blockedUsers, setBlockedUsers] = useState<Member[]>([]);
  const [followerCount, setFollowerCount] = useState(0);
  const [followingCount, setFollowingCount] = useState(0);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<DirectMessage[]>([]);
  const [conversationCreatedAt, setConversationCreatedAt] = useState("");
  const [hasMoreMessages, setHasMoreMessages] = useState(false);
  const [loadingOlderMessages, setLoadingOlderMessages] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sendingMessage, setSendingMessage] = useState(false);
  const sendingMessageRef = useRef(false);
  const [selectedImage, setSelectedImage] = useState<{ uri: string; label: string } | null>(null);
  const [publicProfile, setPublicProfile] = useState<PublicProfile | null>(null);
  const [followStates, setFollowStates] = useState<Record<string, boolean>>({});
  const [followStatusErrors, setFollowStatusErrors] = useState<Record<string, boolean>>({});
  const [followBusyUsers, setFollowBusyUsers] = useState<Set<string>>(new Set());
  const [publicProfilePosts, setPublicProfilePosts] = useState<Post[]>([]);
  const [publicProfileHasMore, setPublicProfileHasMore] = useState(false);
  const [loadingPublicProfileOlder, setLoadingPublicProfileOlder] = useState(false);
  const [profileSections, setProfileSections] = useState<Record<string, boolean>>({});
  const [search, setSearch] = useState<any>(null);
  const [mentionTarget, setMentionTarget] = useState<{ key: string; start: number; end: number; query: string } | null>(null);
  const [mentionSuggestions, setMentionSuggestions] = useState<Member[]>([]);
  const [mentionSuggestionsLoading, setMentionSuggestionsLoading] = useState(false);
  const [composerSelections, setComposerSelections] = useState<Record<string, { start: number; end: number }>>({});
  const [inboxSearchResults, setInboxSearchResults] = useState<Member[]>([]);
  const [blockedUsersLoaded, setBlockedUsersLoaded] = useState(false);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [signupEmail, setSignupEmail] = useState("");
  const [recoveryEmail, setRecoveryEmail] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  const [contextResult, setContextResult] = useState("");
  const [reportTarget, setReportTarget] = useState<ReportTarget | null>(null);
  const [moderationReports, setModerationReports] = useState<ModerationReport[]>([]);
  const reportReturnScreen = useRef("feed");
  const screenRef = useRef(screen);
  const scopeRef = useRef(scope);
  const feedPositionsScopeRef = useRef(scope);
  const postsRef = useRef(posts);
  screenRef.current = screen;
  scopeRef.current = scope;
  if (feedPositionsScopeRef.current !== scope) {
    pendingFeedAnchorRef.current = null;
    feedPostPositionsRef.current = {};
    feedPositionsScopeRef.current = scope;
  }
  postsRef.current = posts;
  useEffect(() => {
    if (screen !== "feed") {
      feedRequestRef.current++;
      feedPollRef.current++;
      setFeedLoading(false);
      pendingFeedAnchorRef.current = null;
      feedPostPositionsRef.current = {};
    }
  }, [screen]);
  useEffect(() => {
    if (screen !== "thread") return;
    const subscription = BackHandler.addEventListener("hardwareBackPress", () => {
      leaveThread();
      return true;
    });
    return () => subscription.remove();
  }, [screen]);
  useEffect(() => {
    if (screen !== "messages") return;
    const subscription = BackHandler.addEventListener("hardwareBackPress", () => {
      leaveConversation();
      return true;
    });
    return () => subscription.remove();
  }, [screen]);
  useEffect(() => {
    const pending = pendingFeedAnchorRef.current;
    if (!pending) return;
    let secondFrame: number | undefined;
    const firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => {
        if (pendingFeedAnchorRef.current === pending) pendingFeedAnchorRef.current = null;
      });
    });
    return () => {
      cancelAnimationFrame(firstFrame);
      if (secondFrame !== undefined) cancelAnimationFrame(secondFrame);
      if (pendingFeedAnchorRef.current === pending) pendingFeedAnchorRef.current = null;
    };
  }, [posts, screen, scope]);
  function updateMe(user: Partial<User> | null) {
    if (!user) { setMe(null); setThemeColorDraft(DEFAULT_ACCENT); activeThemeAccent = DEFAULT_ACCENT; return; }
    setMe(current => current ? { ...current, ...user } as User : user as User);
    if (validHexColor(user.theme_color)) {
      activeThemeAccent = user.theme_color.toLowerCase();
      setThemeColorDraft(activeThemeAccent);
    }
  }
  useEffect(() => {
    let active = true;
    void AccessibilityInfo.isReduceMotionEnabled().then(enabled => {
      if (active) setReduceMotion(enabled);
    }).catch(() => { if (active) setReduceMotion(false); });
    const subscription = AccessibilityInfo.addEventListener("reduceMotionChanged", setReduceMotion);
    return () => { active = false; subscription.remove(); };
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => setSplashVisible(false), 2300);
    return () => clearTimeout(timer);
  }, []);
  useEffect(() => {
    splashGlow.stopAnimation();
    if (reduceMotion || !splashVisible) {
      splashGlow.setValue(0);
      return;
    }
    const animation = Animated.loop(Animated.sequence([
      Animated.timing(splashGlow, { toValue: 1, duration: 900, useNativeDriver: true }),
      Animated.timing(splashGlow, { toValue: 0, duration: 900, useNativeDriver: true }),
    ]));
    animation.start();
    return () => animation.stop();
  }, [reduceMotion, splashVisible, splashGlow]);
  useEffect(() => {
    screenOpacity.stopAnimation();
    screenOffset.stopAnimation();
    if (reduceMotion) {
      screenOpacity.setValue(1);
      screenOffset.setValue(0);
      return;
    }
    screenOpacity.setValue(0.96);
    screenOffset.setValue(4);
    const transition = Animated.parallel([
      Animated.timing(screenOpacity, { toValue: 1, duration: 150, easing: Easing.out(Easing.quad), useNativeDriver: true }),
      Animated.timing(screenOffset, { toValue: 0, duration: 150, easing: Easing.out(Easing.quad), useNativeDriver: true }),
    ]);
    transition.start();
    return () => transition.stop();
  }, [screen, reduceMotion, screenOpacity, screenOffset]);
  useEffect(() => {
    if (!menuOpen) return;
    menuClosePendingRef.current = false;
    menuTranslateX.setValue(menuDrawerWidth);
    menuScrimOpacity.setValue(0);
    if (reduceMotion) {
      menuTranslateX.setValue(0);
      menuScrimOpacity.setValue(1);
      return;
    }
    const opening = Animated.parallel([
      Animated.timing(menuTranslateX, { toValue: 0, duration: 210, easing: Easing.out(Easing.quad), useNativeDriver: true }),
      Animated.timing(menuScrimOpacity, { toValue: 1, duration: 180, useNativeDriver: true }),
    ]);
    opening.start();
    return () => opening.stop();
  }, [menuOpen, reduceMotion, menuDrawerWidth, menuTranslateX, menuScrimOpacity]);
  useEffect(() => {
    const timer = setTimeout(() => {
      const target = menuOpen ? menuCloseButtonRef.current : menuToggleRef.current;
      const tag = target ? findNodeHandle(target) : null;
      if (tag != null) AccessibilityInfo.setAccessibilityFocus(tag);
    }, menuOpen && !reduceMotion ? 240 : 40);
    return () => clearTimeout(timer);
  }, [menuOpen, reduceMotion]);
  activeReduceMotion = reduceMotion;

  async function request(path: string, method = "GET", body?: unknown) {
    const response = await fetch(`${API_URL}${path}`, {
      method,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "Could not connect to Zorlii. Check your API URL and try again.");
    return result;
  }
  async function uploadRequest(path: string, body: FormData, method = "POST") {
    await uploadMultipart(`${API_URL}${path}`, method, body, token);
  }
  function update(key: string, value: string) { setForm(current => ({ ...current, [key]: value })); setError(""); }
  function composerMentionAt(key: string, value: string, cursor: number) {
    if (key !== "post" && !key.startsWith("reply-")) { setMentionTarget(null); return; }
    const beforeCursor = value.slice(0, cursor);
    const match = /(?:^|[\s([{])@([A-Za-z0-9_]{1,24})$/.exec(beforeCursor);
    if (!match) { setMentionTarget(null); return; }
    const start = cursor - match[1].length - 1;
    setMentionTarget({ key, start, end: cursor, query: match[1] });
  }
  function updateComposerText(key: string, value: string) {
    update(key, value);
    const cursor = value.length;
    inputSelectionsRef.current[key] = { start: cursor, end: cursor };
    composerMentionAt(key, value, cursor);
  }
  function updateComposerSelection(key: string, value: string, selection: { start: number; end: number }) {
    inputSelectionsRef.current[key] = selection;
    setComposerSelections(current => ({ ...current, [key]: selection }));
    composerMentionAt(key, value, selection.end);
  }
  function selectMention(person: Member) {
    if (!mentionTarget) return;
    const { key, start, end } = mentionTarget;
    const draft = form[key] || "";
    const inserted = `@${person.username} `;
    const next = `${draft.slice(0, start)}${inserted}${draft.slice(end)}`;
    const cursor = start + inserted.length;
    update(key, next);
    const selection = { start: cursor, end: cursor };
    inputSelectionsRef.current[key] = selection;
    setComposerSelections(current => ({ ...current, [key]: selection }));
    setMentionTarget(null);
    setMentionSuggestions([]);
    requestAnimationFrame(() => {
      const input = key === "post" ? composerRef.current : composerInputRefs.current[key];
      input?.focus();
      input?.setNativeProps({ selection });
    });
  }
  function fail(e: unknown) { setError(e instanceof Error ? e.message : "Something went wrong."); }
  async function hydrateFollowStates(people: Member[]) {
    const listed = people.filter(person => person.username);
    setFollowStates(current => {
      const next = { ...current };
      listed.forEach(person => { delete next[person.username.toLowerCase()]; });
      return next;
    });
    setFollowStatusErrors(current => {
      const next = { ...current };
      listed.forEach(person => { delete next[person.username.toLowerCase()]; });
      return next;
    });
    await Promise.all(listed.map(async person => {
      const key = person.username.toLowerCase();
      const requestId = (followLookupRequestRef.current[key] || 0) + 1;
      followLookupRequestRef.current[key] = requestId;
      try {
        const result = await request(`/api/users/${encodeURIComponent(person.username)}`);
        if (followLookupRequestRef.current[key] !== requestId) return;
        setFollowStates(current => ({ ...current, [key]: Boolean(result.user.following) }));
        setFollowStatusErrors(current => { const next = { ...current }; delete next[key]; return next; });
      } catch {
        if (followLookupRequestRef.current[key] === requestId) setFollowStatusErrors(current => ({ ...current, [key]: true }));
      }
    }));
  }
  async function toggleFollow(username: string) {
    const key = username.toLowerCase();
    if (followStates[key] === undefined || followBusyUsers.has(key)) return;
    const requestId = (followLookupRequestRef.current[key] || 0) + 1;
    followLookupRequestRef.current[key] = requestId;
    setFollowBusyUsers(current => new Set(current).add(key));
    try {
      const result = await request(`/api/users/${encodeURIComponent(username)}/follow`, "POST");
      if (followLookupRequestRef.current[key] !== requestId) return;
      setFollowStates(current => ({ ...current, [key]: Boolean(result.following) }));
      setFollowStatusErrors(current => { const next = { ...current }; delete next[key]; return next; });
    } catch (e) { fail(e); }
    finally { setFollowBusyUsers(current => { const next = new Set(current); next.delete(key); return next; }); }
  }
  function replacePostEverywhere(updated: Post) {
    postsRef.current = postsRef.current.map(post => post.id === updated.id ? updated : post);
    setPosts(postsRef.current);
    setProfilePosts(current => current.map(post => post.id === updated.id ? updated : post));
    setPublicProfilePosts(current => current.map(post => post.id === updated.id ? updated : post));
    setHashtagPosts(current => current.map(post => post.id === updated.id ? updated : post));
    setSearch((current: any) => current ? { ...current, posts: (current.posts || []).map((post: Post) => post.id === updated.id ? updated : post) } : current);
  }
  function removePostEverywhere(postId: number) {
    postsRef.current = postsRef.current.filter(post => post.id !== postId);
    setPosts(postsRef.current);
    setProfilePosts(current => current.filter(post => post.id !== postId));
    setPublicProfilePosts(current => current.filter(post => post.id !== postId));
    setHashtagPosts(current => current.filter(post => post.id !== postId));
    setSearch((current: any) => current ? { ...current, posts: (current.posts || []).filter((post: Post) => post.id !== postId) } : current);
    setReplies(current => { const next = { ...current }; delete next[postId]; return next; });
    setContentMenu(current => current?.type === "post" && current.id === postId ? null : current);
  }
  function showImage(uri: string, label: string) {
    setSelectedImage({ uri, label });
  }
  async function openPublicProfile(username: string) {
    if (username.toLowerCase() === me?.username.toLowerCase()) {
      loadProfile();
      return;
    }
    profileReturnScreenRef.current = screen === "social-profile" ? profileReturnScreenRef.current : screen;
    const sameProfile = publicProfileUsernameRef.current === username.toLowerCase();
    publicProfileUsernameRef.current = username.toLowerCase();
    setPublicProfile(null);
    if (!sameProfile) {
      publicProfileLoadedOlderRef.current = false;
      setPublicProfilePosts([]);
      setPublicProfileHasMore(false);
    }
    setScreen("social-profile");
    setLoading(true);
    try {
      const [profileData, postData] = await Promise.all([
        request(`/api/users/${encodeURIComponent(username)}`),
        request(`/api/users/${encodeURIComponent(username)}/posts`),
      ]);
      if (publicProfileUsernameRef.current !== username.toLowerCase()) return;
      setPublicProfile(profileData.user);
      followLookupRequestRef.current[username.toLowerCase()] = (followLookupRequestRef.current[username.toLowerCase()] || 0) + 1;
      setFollowStates(current => ({ ...current, [username.toLowerCase()]: Boolean(profileData.user.following) }));
      setFollowStatusErrors(current => { const next = { ...current }; delete next[username.toLowerCase()]; return next; });
      setPublicProfilePosts(current => sameProfile ? mergeProfilePosts(current, postData.posts) : postData.posts);
      if (!publicProfileLoadedOlderRef.current) {
        setPublicProfileHasMore(Boolean(postData.has_more));
      }
    } catch (e) { fail(e); }
    finally { setLoading(false); }
  }
  async function loadOlderProfilePosts(isPublic: boolean) {
    const username = isPublic ? publicProfile?.username : me?.username;
    const currentPosts = isPublic ? publicProfilePosts : profilePosts;
    const hasMore = isPublic ? publicProfileHasMore : profileHasMore;
    const isLoading = isPublic ? loadingPublicProfileOlder : loadingProfileOlder;
    if (!username || !hasMore || isLoading || !currentPosts.length) return;
    const oldestId = Math.min(...currentPosts.map(post => post.id));
    const userId = profileUserRef.current;
    const setBusy = isPublic ? setLoadingPublicProfileOlder : setLoadingProfileOlder;
    setBusy(true);
    try {
      const data = await request(`/api/users/${encodeURIComponent(username)}/posts?before_id=${oldestId}`);
      if (profileUserRef.current !== userId) return;
      if (isPublic) {
        if (publicProfileUsernameRef.current !== username.toLowerCase()) return;
        publicProfileLoadedOlderRef.current = true;
        setPublicProfilePosts(current => mergeProfilePosts(current, data.posts));
        setPublicProfileHasMore(Boolean(data.has_more));
      } else {
        profileLoadedOlderRef.current = true;
        setProfilePosts(current => mergeProfilePosts(current, data.posts));
        setProfileHasMore(Boolean(data.has_more));
      }
    } catch (e) { fail(e); }
    finally { setBusy(false); }
  }
  async function openSocialList(username: string, kind: SocialKind, offset = 0) {
    const requestId = offset ? socialListRequestRef.current : ++socialListRequestRef.current;
    if (!offset) {
      setSocialList({ username, kind, users: [], count: 0 });
      setScreen(`social-${kind}`);
    }
    setSocialListLoading(true);
    setError("");
    try {
      const data = await request(`/api/users/${encodeURIComponent(username)}/${kind}?limit=30&offset=${offset}`);
      if (requestId !== socialListRequestRef.current) return;
      setSocialList(current => ({ username, kind, users: offset && current ? [...current.users, ...data.users] : data.users, count: data.count }));
      void hydrateFollowStates(data.users);
    } catch (e) { if (requestId === socialListRequestRef.current) fail(e); }
    finally { if (requestId === socialListRequestRef.current) setSocialListLoading(false); }
  }
  async function openHashtag(tag: string, beforeId?: number) {
    const requestId = beforeId ? hashtagRequestRef.current : ++hashtagRequestRef.current;
    if (!beforeId) {
      setHashtag(tag);
      setHashtagPosts([]);
      setHashtagHasMore(false);
      setScreen("hashtag");
    }
    setHashtagLoading(true);
    setError("");
    try {
      const data = await request(`/api/hashtags/${encodeURIComponent(tag)}${beforeId ? `?before_id=${beforeId}` : ""}`);
      if (requestId !== hashtagRequestRef.current) return;
      setHashtagPosts(current => beforeId ? [...current, ...data.posts] : data.posts);
      setHashtagHasMore(Boolean(data.has_more) && data.posts.length > 0);
    } catch (e) { if (requestId === hashtagRequestRef.current) fail(e); }
    finally { if (requestId === hashtagRequestRef.current) setHashtagLoading(false); }
  }
  function taggedText(body: string) {
    const parts: React.ReactNode[] = [];
    const mentionPattern = /(^|[^A-Za-z0-9_@.])@([A-Za-z0-9_]{3,24})(?![A-Za-z0-9_])|(^|[^\p{L}\p{N}_#@])#([\p{L}\p{N}_]{1,100})(?![\p{L}\p{N}_])/gu;
    let cursor = 0;
    let match: RegExpExecArray | null;
    while ((match = mentionPattern.exec(body)) !== null) {
      const mentionStart = match.index + (match[1] || match[3] || "").length;
      if (mentionStart > cursor) parts.push(body.slice(cursor, mentionStart));
      const username = match[2], tag = match[4];
      parts.push(<Text key={`${mentionStart}-${username || tag}`} accessibilityRole="link"
        accessibilityLabel={username ? `View @${username}'s profile` : `View posts tagged #${tag}`}
        style={[styles.mention, { color: readableAccent(activeThemeAccent) }]}
        onPress={event => { event.stopPropagation(); if (username) void openPublicProfile(username); else void openHashtag(tag); }}>{username ? `@${username}` : `#${tag}`}</Text>);
      cursor = mentionPattern.lastIndex;
    }
    if (cursor < body.length) parts.push(body.slice(cursor));
    return parts;
  }
  function warnPushCleanup() {
    Alert.alert("Notification cleanup incomplete", "We couldn't confirm that activity alerts were removed for the previous account on this device. You can sign in to that account and try signing out again when your connection is working.");
  }
  async function waitForPushCleanup(operation: Promise<unknown>) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        operation.then(() => true, () => false),
        new Promise<boolean>(resolve => { timer = setTimeout(() => resolve(false), 8000); }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }
  async function registerPushToken(authToken: string, explicitRetry = false) {
    if (!canRegisterPushToken(Platform.OS, Device.isDevice)) return false;
    if (pushSessionRef.current !== authToken) return false;
    const generation = pushSessionGenerationRef.current;
    if (explicitRetry) pushReturnRetryUsedRef.current = false;
    while (pushRegistrationPromiseRef.current) {
      const pending = pushRegistrationPromiseRef.current;
      const sameSession = pushRegistrationOwnerRef.current === authToken && pushRegistrationGenerationRef.current === generation;
      if (sameSession && !explicitRetry) return pending;
      if (!sameSession && !pushPostingRef.current) break;
      await pending.catch(() => false);
      if (pushSessionRef.current !== authToken || pushSessionGenerationRef.current !== generation) return false;
      if (pushRegistrationPromiseRef.current === pending) {
        pushRegistrationPromiseRef.current = null;
        pushPostingRef.current = false;
      }
    }
    const isCurrentSession = () => pushSessionRef.current === authToken && pushSessionGenerationRef.current === generation;
    const registration = (async () => {
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("default", {
        name: "Activity alerts",
        importance: Notifications.AndroidImportance.HIGH,
      });
    }
    if (!isCurrentSession()) return false;
    let permission = await Notifications.getPermissionsAsync();
    if (!isCurrentSession()) return false;
    if (permission.status !== "granted" && permission.canAskAgain !== false) permission = await Notifications.requestPermissionsAsync();
    if (!isCurrentSession()) return false;
    if (permission.status !== "granted") return explicitRetry && permission.canAskAgain === false ? "blocked" as const : false;
    if (pushTokenRef.current) return true;
    const projectId = Constants.easConfig?.projectId || Constants.expoConfig?.extra?.eas?.projectId;
    if (!projectId) throw new Error("Link this app to an EAS project before enabling phone notifications.");
    let expoToken: string;
    try {
      expoToken = (await (Platform.OS === "android"
        ? retryTransientPushOperation(() => {
          if (!isCurrentSession()) throw new Error("Notification session ended.");
          return Notifications.getExpoPushTokenAsync({ projectId });
        })
        : Notifications.getExpoPushTokenAsync({ projectId }))).data;
      if (!isCurrentSession()) return false;
      pushRetryPendingRef.current = false;
    } catch (error) {
      if (!isCurrentSession()) return false;
      pushRetryPendingRef.current = Platform.OS === "android" && isTransientPushServiceUnavailable(error);
      throw error;
    }
    pushPostingRef.current = true;
    let response: Response;
    try {
      response = await fetch(`${API_URL}/api/push-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
        body: JSON.stringify({ token: expoToken, platform: Platform.OS }),
      });
    } catch (error) {
      if (!isCurrentSession()) {
        warnPushCleanup();
        return false;
      }
      throw error;
    }
    if (!isCurrentSession()) {
      if (response.ok) {
        try {
          const cleanup = await fetch(`${API_URL}/api/push-token`, {
            method: "DELETE",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
            body: JSON.stringify({ token: expoToken, platform: Platform.OS }),
          });
          if (!cleanup.ok) warnPushCleanup();
        } catch {
          warnPushCleanup();
        }
      }
      return false;
    }
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.detail || "Could not register this device for phone notifications.");
    }
    pushTokenRef.current = expoToken;
    pushRetryPendingRef.current = false;
    pushReturnRetryUsedRef.current = false;
    return true;
    })();
    pushRegistrationPromiseRef.current = registration;
    pushRegistrationOwnerRef.current = authToken;
    pushRegistrationGenerationRef.current = generation;
    try { return await registration; }
    finally { if (pushRegistrationPromiseRef.current === registration) { pushRegistrationPromiseRef.current = null; pushPostingRef.current = false; } }
  }
  async function loadFeed(nextScope = scope, silent = false) {
    const requestId = ++feedRequestRef.current;
    const requestedScope = nextScope;
    scopeRef.current = requestedScope;
    feedPollRef.current++;
    setScope(requestedScope);
    if (!silent) setFeedLoading(true);
    try {
      const data = await request(`/api/feed?scope=${requestedScope}`);
      if (requestId !== feedRequestRef.current || scopeRef.current !== requestedScope) return;
      if (silent) {
        const anchor = feedInsertionAnchor(postsRef.current, data.posts, feedPostPositionsRef.current);
        if (anchor) pendingFeedAnchorRef.current = { ...anchor, scope: requestedScope };
      }
      postsRef.current = data.posts;
      setPosts(data.posts);
      feedPollRef.current++;
    } catch (e) {
      if (requestId === feedRequestRef.current) fail(e);
    } finally {
      if (requestId === feedRequestRef.current) setFeedLoading(false);
    }
  }
  async function loadInbox() {
    screenRef.current = "inbox";
    setScreen("inbox");
    setLoading(true);
    try { const data = await request("/api/conversations"); if (screenRef.current === "inbox") setConversations(data.conversations); }
    catch (e) { fail(e); } finally { setLoading(false); }
  }
  function leaveConversation() {
    conversationGenerationRef.current++;
    activeConversationIdRef.current = null;
    messageRestoreOffsetRef.current = null;
    messageLatestTargetRef.current = null;
    setLoadingMessages(false);
    setLoadingOlderMessages(false);
    setError("");
    void loadInbox();
  }
  async function loadProfile() {
    setScreen("profile");
    if (!me) return;
    try {
      const [postData, followerData, followingData, blockData, meData] = await Promise.all([
        request(`/api/users/${me.username}/posts`),
        request(`/api/users/${me.username}/followers?limit=1`),
        request(`/api/users/${me.username}/following?limit=1`),
        request("/api/blocks"),
        request("/api/me"),
      ]);
      if (profileUserRef.current !== me.id) return;
      setProfilePosts(current => mergeProfilePosts(current, postData.posts));
      if (!profileLoadedOlderRef.current) {
        setProfileHasMore(Boolean(postData.has_more));
      }
      updateMe(meData.user);
      setActivityCounts(meData.user.activity_counts || null);
      setBlockedUsers(blockData.users);
      setFollowerCount(followerData.count);
      setFollowingCount(followingData.count);
    }
    catch (e) { fail(e); }
  }
  async function loadSettings() {
    setScreen("settings");
    try { setBlockedUsers((await request("/api/blocks")).users); }
    catch (e) { fail(e); }
  }
  async function saveProfileSection(section: "profile" | "privacy") {
    if (section === "profile" && !/^[a-z0-9_]{3,24}$/.test((form.username || me?.username || "").trim().toLowerCase())) {
      setError("Username must be 3–24 lowercase letters, numbers, or underscores.");
      return;
    }
    const body = section === "profile" ? {
      username: (form.username || me?.username || "").trim().toLowerCase(),
      display_name: form.display_name || me?.display_name,
      bio: form.bio ?? me?.bio,
      interests: (form.interests ?? me?.interests.join(",") ?? "").split(",").map(x => x.trim()).filter(Boolean),
    } : {
      recommendations_consent: form.recommendations_consent ? form.recommendations_consent === "true" : me?.recommendations_consent,
      context_assistance_consent: form.context_assistance_consent ? form.context_assistance_consent === "true" : me?.context_assistance_consent,
    };
    try {
      const result = await request("/api/profile", "PATCH", body);
      updateMe(result.user);
      Alert.alert("Saved", section === "profile" ? "Your profile has been updated." : "Your privacy choices have been updated.");
    } catch (e) { fail(e); }
  }
  async function saveThemeColor() {
    const color = themeColorDraft.trim();
    if (!validHexColor(color)) { setError("Enter a six-digit hex colour such as #A47DFF."); return; }
    try {
      const result = await request("/api/settings/theme", "PATCH", { theme_color: color.toLowerCase() });
      updateMe(result.user);
      Alert.alert("Appearance saved", "Your accent colour is now applied to your account.");
    } catch (e) { fail(e); }
  }
  async function pickAvatar() {
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert("Photo access needed", "Allow photo-library access to choose a profile photo.");
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"], allowsEditing: true, aspect: [1, 1], quality: 0.95,
      });
      if (result.canceled) return;
      const asset = result.assets[0];
      const contentType = asset.mimeType?.toLowerCase() || "application/octet-stream";
      const body = new FormData() as NativeUploadFormData;
      body.append("file", {
        uri: asset.uri,
        name: nativeUploadName(asset.fileName, "profile", contentType),
        type: contentType,
      });
      await uploadRequest("/api/profile/avatar", body, "PUT");
      updateMe((await request("/api/me")).user);
      Alert.alert("Photo updated", "Your profile photo is ready.");
    } catch (e) { fail(e); }
  }
  async function pickPostMedia(replyPostId?: number) {
    try {
      const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!permission.granted) {
        Alert.alert("Media access needed", "Allow photo-library access to attach media to a post.");
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images", "videos"], allowsMultipleSelection: true, selectionLimit: 4, quality: 1,
      });
      if (!result.canceled) {
        if (replyPostId !== undefined) setReplyMediaByPost(current => ({ ...current, [replyPostId]: result.assets }));
        else setPostMedia(result.assets);
      }
    } catch (e) { fail(e); }
  }
  function confirmAvatarRemoval() {
    Alert.alert("Remove profile photo?", "Your initials will appear instead.", [
      { text: "Cancel", style: "cancel" },
      { text: "Remove photo", style: "destructive", onPress: async () => {
        try {
          await request("/api/profile/avatar", "DELETE");
          updateMe((await request("/api/me")).user);
        } catch (e) { fail(e); }
      } },
    ]);
  }
  async function loadNotifications() {
    setLoading(true);
    try {
      const data = await request("/api/notifications");
      setNotifications(data.notifications);
      setUnreadNotifications(data.unread_count);
    } catch (e) { fail(e); }
    finally { setLoading(false); }
  }
  async function openMentionTarget(item: NotificationItem) {
    if (!item.post_id) return;
    try {
      const result = await request(`/api/posts/${item.post_id}`);
      await openThread(result.post, item.reply_id || undefined);
    } catch (e) { fail(e); }
  }
  async function markNotificationRead(id: number) {
    try { await request(`/api/notifications/${id}/read`, "PATCH"); await loadNotifications(); }
    catch (e) { fail(e); }
  }
  async function markAllNotificationsRead() {
    try { await request("/api/notifications/read", "POST"); await loadNotifications(); }
    catch (e) { fail(e); }
  }
  async function openThread(post: Post, replyId?: number) {
    if (screen !== "thread") threadReturnScreenRef.current = screen;
    threadRequestRef.current++;
    threadTargetReplyRef.current = replyId ?? null;
    threadRefreshBusyRef.current = false;
    threadRefreshAgainRef.current = false;
    threadLoadingMoreRef.current = false;
    setThreadRefreshing(false);
    setThreadPost(post);
    setThreadReplies([]);
    setThreadHasMore(false);
    setThreadNextAfterId(null);
    setThreadLoading(true);
    setThreadLoadingMore(false);
    setThreadError("");
    setScreen("thread");
    await refreshThread(true, replyId, post);
  }
  async function refreshThread(initial = false, targetReplyId?: number, fallbackPost: Post | null = threadPost) {
    const requestId = threadRequestRef.current;
    const post = initial ? fallbackPost : threadPost;
    if (!post) return;
    if (threadRefreshBusyRef.current || threadLoadingMoreRef.current) { threadRefreshAgainRef.current = true; return; }
    threadRefreshBusyRef.current = true;
    setThreadLoading(initial);
    setThreadRefreshing(!initial);
    setThreadError("");
    try {
      const result = await readThreadPages<Post, Reply>(
        cursor => request(`/api/posts/${post.id}${cursor === undefined ? "" : `?after_id=${encodeURIComponent(cursor)}&limit=100`}`),
        post, initial, targetReplyId,
      );
      if (requestId !== threadRequestRef.current) return;
      setThreadPost(result.post);
      setThreadReplies(result.replies);
      setThreadHasMore(result.hasMore);
      setThreadNextAfterId(result.nextAfterId);
    } catch (e) {
      if (requestId === threadRequestRef.current) {
        setThreadError(e instanceof Error ? e.message : "The thread could not be refreshed.");
      }
    } finally {
      if (requestId === threadRequestRef.current) {
        setThreadLoading(false);
        setThreadRefreshing(false);
      }
      if (requestId === threadRequestRef.current) {
        threadRefreshBusyRef.current = false;
        if (threadRefreshAgainRef.current) {
          threadRefreshAgainRef.current = false;
          requestAnimationFrame(() => { void threadRefreshLatestRef.current(); });
        }
      }
    }
  }
  threadRefreshLatestRef.current = () => refreshThread();
  function leaveThread() {
    threadRequestRef.current++;
    threadTargetReplyRef.current = null;
    threadLoadingMoreRef.current = false;
    setThreadError("");
    setScreen(threadReturnScreenRef.current);
  }
  async function loadMoreThreadReplies() {
    const post = threadPost;
    const cursor = threadNextAfterId ?? threadReplies.at(-1)?.id;
    if (!post || !threadHasMore || threadLoadingMoreRef.current || threadRefreshBusyRef.current) return;
    if (!cursor) { setThreadError("The next reply page could not be located. Try reloading this thread."); return; }
    const requestId = threadRequestRef.current;
    threadLoadingMoreRef.current = true;
    setThreadLoadingMore(true);
    setThreadError("");
    try {
      const result = await request(`/api/posts/${post.id}?after_id=${encodeURIComponent(cursor)}&limit=100`);
      if (requestId !== threadRequestRef.current) return;
      const incoming = (result.replies || []) as Reply[];
      const known = new Set(threadReplies.map(reply => String(reply.id)));
      const added = incoming.filter(reply => !known.has(String(reply.id)));
      const nextReplies = [...threadReplies, ...added];
      const nextHasMore = typeof result.has_more === "boolean" ? result.has_more : Number(result.post?.reply_count || post.reply_count) > nextReplies.length;
      const nextCursor = result.next_after_id ?? nextReplies.at(-1)?.id ?? null;
      if (nextHasMore && (!added.length || nextCursor === cursor)) {
        setThreadError("The server did not return the next reply page. Your draft is still here; try again shortly.");
        return;
      }
      setThreadReplies(nextReplies);
      setThreadPost(result.post || post);
      setThreadHasMore(nextHasMore);
      setThreadNextAfterId(nextCursor);
    } catch (e) {
      if (requestId === threadRequestRef.current) setThreadError(e instanceof Error ? e.message : "More replies could not be loaded.");
    } finally {
      if (requestId === threadRequestRef.current) {
        threadLoadingMoreRef.current = false;
        setThreadLoadingMore(false);
        if (threadRefreshAgainRef.current) {
          threadRefreshAgainRef.current = false;
          requestAnimationFrame(() => { void threadRefreshLatestRef.current(); });
        }
      }
    }
  }
  function scrollToLatestMessageWhenLaidOut(id: number | undefined) {
    messageLatestTargetRef.current = id ?? null;
    if (id !== undefined && messagePositionsRef.current.has(id)) {
      requestAnimationFrame(() => {
        if (messageLatestTargetRef.current !== id) return;
        messageScrollRef.current?.scrollToEnd({ animated: false });
        messageLatestTargetRef.current = null;
      });
    }
  }
  function onMessageLayout(id: number, top: number) {
    messagePositionsRef.current.set(id, top);
    const restore = messageRestoreOffsetRef.current;
    if (restore?.id === id && top !== restore.top) {
      const conversation = activeConversationIdRef.current;
      messageRestoreOffsetRef.current = null;
      requestAnimationFrame(() => {
        if (activeConversationIdRef.current !== conversation) return;
        messageScrollRef.current?.scrollTo({ y: Math.max(0, restore.offset + top - restore.top), animated: false });
      });
    } else if (messageLatestTargetRef.current === id) {
      scrollToLatestMessageWhenLaidOut(id);
    }
  }
  async function loadConversation(id: number) {
    const isSameConversation = activeConversationIdRef.current === id;
    const generation = ++conversationGenerationRef.current;
    activeConversationIdRef.current = id;
    setConversationId(id);
    setScreen("messages");
    setForm(current => ({ ...current, message: messageDraftsRef.current[id] || "" }));
    messagePositionsRef.current.clear();
    messageRestoreOffsetRef.current = null;
    messageLatestTargetRef.current = isSameConversation ? messagesRef.current[messagesRef.current.length - 1]?.id ?? null : null;
    if (!isSameConversation) {
      messagesRef.current = [];
      setMessages([]);
      setConversationCreatedAt(conversations.find(item => item.id === id)?.created_at || "");
      setHasMoreMessages(false);
      messageScrollYRef.current = 0;
    }
    setLoadingMessages(true);
    try {
      const data = await request(`/api/conversations/${id}/messages`);
      if (activeConversationIdRef.current !== id || conversationGenerationRef.current !== generation) return;
      const previousCount = messagesRef.current.length;
      const nextMessages = isSameConversation ? mergeMessages(messagesRef.current, data.messages) : data.messages;
      if (!isSameConversation || !previousCount) scrollToLatestMessageWhenLaidOut(nextMessages[nextMessages.length - 1]?.id);
      messagesRef.current = nextMessages;
      setMessages(nextMessages);
      if (!isSameConversation || previousCount <= data.messages.length) {
        setHasMoreMessages(Boolean(data.has_more));
      }
      setConversationCreatedAt(data.conversation_created_at || conversations.find(item => item.id === id)?.created_at || "");
    }
    catch (e) { if (activeConversationIdRef.current === id && conversationGenerationRef.current === generation) fail(e); }
    finally { if (activeConversationIdRef.current === id && conversationGenerationRef.current === generation) setLoadingMessages(false); }
  }
  async function refreshConversationMessages(id: number, scrollToLatest = false) {
    const generation = conversationGenerationRef.current;
    const data = await request(`/api/conversations/${id}/messages`);
    if (activeConversationIdRef.current !== id || conversationGenerationRef.current !== generation) return;
    const previousCount = messagesRef.current.length;
    const nextMessages = mergeMessages(messagesRef.current, data.messages);
    if (scrollToLatest) scrollToLatestMessageWhenLaidOut(nextMessages[nextMessages.length - 1]?.id);
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    if (previousCount <= data.messages.length) {
      setHasMoreMessages(Boolean(data.has_more));
    }
    if (data.conversation_created_at) setConversationCreatedAt(data.conversation_created_at);
  }
  async function loadOlderMessages() {
    if (!hasMoreMessages || loadingOlderMessages || conversationId === null || messages.length === 0) return;
    const id = conversationId;
    const generation = conversationGenerationRef.current;
    const oldestId = messages[0].id;
    setLoadingOlderMessages(true);
    try {
      const data = await request(`/api/conversations/${id}/messages?before_id=${oldestId}`);
      if (activeConversationIdRef.current !== id || conversationGenerationRef.current !== generation) return;
      const oldTop = messagePositionsRef.current.get(oldestId);
      if (data.messages.length && oldTop !== undefined) {
        messageLatestTargetRef.current = null;
        messageRestoreOffsetRef.current = { id: oldestId, top: oldTop, offset: messageScrollYRef.current };
      }
      const nextMessages = mergeMessages(data.messages, messagesRef.current);
      messagesRef.current = nextMessages;
      setMessages(nextMessages);
      setHasMoreMessages(Boolean(data.has_more));
      if (data.conversation_created_at) setConversationCreatedAt(data.conversation_created_at);
    } catch (e) { if (activeConversationIdRef.current === id && conversationGenerationRef.current === generation) fail(e); }
    finally { if (activeConversationIdRef.current === id && conversationGenerationRef.current === generation) setLoadingOlderMessages(false); }
  }
  function resetConversationState() {
    socialListRequestRef.current++;
    hashtagRequestRef.current++;
    setSocialList(null);
    setHashtag("");
    setHashtagPosts([]);
    setHashtagHasMore(false);
    conversationGenerationRef.current++;
    activeConversationIdRef.current = null;
    messagesRef.current = [];
    messageDraftsRef.current = {};
    messageDraftVersionRef.current = {};
    setConversationId(null);
    setMessages([]);
    setConversationCreatedAt("");
    setHasMoreMessages(false);
    setLoadingMessages(false);
    setLoadingOlderMessages(false);
    messageLatestTargetRef.current = null;
    messagePositionsRef.current.clear();
    messageRestoreOffsetRef.current = null;
    publicProfileUsernameRef.current = "";
    profileUserRef.current = null;
    profileLoadedOlderRef.current = false;
    publicProfileLoadedOlderRef.current = false;
    setPublicProfile(null);
    setPublicProfilePosts([]);
    setPublicProfileHasMore(false);
    setProfilePosts([]);
    setProfileHasMore(false);
    setActivityCounts(null);
  }
  async function acceptTerms() {
    try {
      const result = await request("/api/terms/accept", "POST", { accepted: true });
      updateMe(result.user);
      setScreen("feed");
      await loadFeed();
    } catch (e) { fail(e); }
  }
  function openReport(target: ReportTarget) {
    reportReturnScreen.current = screen;
    setReportTarget(target);
    setForm(current => ({ ...current, report_reason: "", report_details: "" }));
    setScreen("report");
  }
  async function submitReport() {
    if (!reportTarget || !form.report_reason) {
      setError("Choose a reason for this report.");
      return;
    }
    try {
      const result = await request("/api/reports", "POST", {
        target_type: reportTarget.target_type,
        target_id: reportTarget.target_id,
        reason: form.report_reason,
        details: form.report_details || "",
      });
      setReportTarget(null);
      setScreen(reportReturnScreen.current);
      setError(result.message);
    } catch (e) { fail(e); }
  }
  async function loadModerationReports() {
    try { setModerationReports((await request("/api/moderation/reports")).reports); }
    catch (e) { fail(e); }
  }
  async function unblockUser(username: string) {
    try {
      await request(`/api/users/${encodeURIComponent(username)}/block`, "POST");
      setBlockedUsers(current => current.filter(person => person.username !== username));
    } catch (e) { fail(e); }
  }
  async function updateModerationReport(id: number, status: "reviewed" | "dismissed") {
    try {
      await request(`/api/moderation/reports/${id}`, "PATCH", { status });
      setModerationReports(current => current.filter(report => report.id !== id));
    } catch (e) { fail(e); }
  }
  async function removeReportedPost(report: ModerationReport) {
    if (!report.post_id) return;
    Alert.alert("Remove reported post?", "This permanently removes the post and its uploaded media.", [
      { text: "Cancel", style: "cancel" },
      { text: "Remove post", style: "destructive", onPress: async () => {
        try {
          await request(`/api/moderation/posts/${report.post_id}`, "DELETE");
          setModerationReports(current => current.filter(item => item.post_id !== report.post_id));
        } catch (e) { fail(e); }
      } },
    ]);
  }
  function removeModeratedPost(post: Post) {
    if (!me?.is_moderator) return;
    Alert.alert("Remove this post?", "This permanently removes the post and its uploaded media.", [
      { text: "Cancel", style: "cancel" },
      { text: "Remove post", style: "destructive", onPress: async () => {
        try {
          await request(`/api/moderation/posts/${post.id}`, "DELETE");
          removePostEverywhere(post.id);
          setModerationReports(current => current.filter(item => item.post_id !== post.id));
        } catch (e) { fail(e); }
      } },
    ]);
  }
  function showSafetyOptions(person: { id: number; username: string }, post?: Post) {
    const reportOptions = [
      ...(post ? [{ text: "Report post", onPress: () => openReport({ target_type: "post", target_id: post.id, label: "post" }) }] : []),
      { text: "Report account", onPress: () => openReport({ target_type: "user", target_id: person.id, label: `@${person.username}` }) },
      { text: "Cancel", style: "cancel" as const },
    ];
    Alert.alert("Safety options", `Choose an action for @${person.username}.`, [
      { text: "Report", onPress: () => Alert.alert("Report", "What would you like to report?", reportOptions) },
      { text: `Block @${person.username}`, style: "destructive", onPress: () => Alert.alert(
        `Block @${person.username}?`,
        "Their posts and messages will no longer be available to you, and existing follows between you will be removed.",
        [
          { text: "Cancel", style: "cancel" },
          { text: "Block", style: "destructive", onPress: async () => {
            try {
              await request(`/api/users/${encodeURIComponent(person.username)}/block`, "POST");
              setBlockedUsers(current => current.some(item => item.username === person.username)
                ? current : [...current, { id: person.id, username: person.username, display_name: person.username, bio: "" }]);
              postsRef.current = postsRef.current.filter(item => item.author.id !== person.id);
              setPosts(postsRef.current);
              setProfilePosts(current => current.filter(item => item.author.id !== person.id));
              setPublicProfilePosts(current => current.filter(item => item.author.id !== person.id));
              setHashtagPosts(current => current.filter(item => item.author.id !== person.id));
              Alert.alert("Account blocked", `@${person.username} has been blocked.`);
            } catch (e) { fail(e); }
          } },
        ],
      ) },
      { text: "Cancel", style: "cancel" },
    ]);
  }
  async function enterApp(authToken: string) {
    pushSessionGenerationRef.current++;
    pushSessionRef.current = authToken;
    pushTokenRef.current = null;
    pushRetryPendingRef.current = false;
    pushReturnRetryUsedRef.current = false;
    setToken(authToken);
    await SecureStore.setItemAsync("zorlii_session", authToken);
    try {
      const response = await fetch(`${API_URL}/api/me`, { headers: { Authorization: `Bearer ${authToken}` } });
      if (!response.ok) throw new Error("Please sign in again.");
      const data = await response.json();
      profileUserRef.current = data.user.id;
      updateMe(data.user);
      setActivityCounts(data.user.activity_counts || null);
      if (!data.user.terms_accepted) {
        setScreen("terms");
        return;
      }
      const feedResponse = await fetch(`${API_URL}/api/feed?scope=all`, { headers: { Authorization: `Bearer ${authToken}` } });
      if (feedResponse.ok) {
        postsRef.current = (await feedResponse.json()).posts;
        setPosts(postsRef.current);
      }
      setScreen("feed");
    } catch (e) { if (pushSessionRef.current === authToken) pushSessionRef.current = ""; await SecureStore.deleteItemAsync("zorlii_session"); resetConversationState(); setToken(""); fail(e); }
  }
  useEffect(() => {
    (async () => {
      const saved = await SecureStore.getItemAsync("zorlii_session");
      if (saved) await enterApp(saved);
    })();
  }, []);
  useEffect(() => {
    if (!token || !me?.terms_accepted) return;
    let active = true;
    void registerPushToken(token).catch(error => {
      if (!active) return;
      if (isTransientPushServiceUnavailable(error)) setError(pushRegistrationErrorMessage(error));
      else fail(error);
    });
    return () => { active = false; };
  }, [token, me?.terms_accepted]);
  useEffect(() => {
    if (!token || !me?.terms_accepted) return;
    const openNotificationTarget = (data: Record<string, unknown> = {}) => {
      if (data.screen === "activities") {
        setScreen("notifications");
        void loadNotifications();
      } else if (data.screen === "inbox" && Number.isSafeInteger(Number(data.conversation_id))) {
        void loadConversation(Number(data.conversation_id));
      }
    };
    const subscription = Notifications.addNotificationResponseReceivedListener(response => {
      openNotificationTarget(response.notification.request.content.data);
    });
    void Notifications.getLastNotificationResponseAsync().then(response => {
      if (response) {
        openNotificationTarget(response.notification.request.content.data);
        void Notifications.clearLastNotificationResponseAsync();
      }
    }).catch(error => console.warn("Could not read the last notification response.", error));
    return () => subscription.remove();
  }, [token, me?.terms_accepted]);
  useEffect(() => {
    const handleUrl = ({ url }: { url: string }) => {
      if (/\/(activities|notifications)(?:[/?#]|$)/i.test(url)) {
        if (!token) { setScreen("login"); return; }
        setScreen("notifications");
        void loadNotifications();
        return;
      }
      const conversationMatch = url.match(/\/conversations?\/(\d+)/i);
      if (conversationMatch) {
        if (!token) { setScreen("login"); return; }
        void loadConversation(Number(conversationMatch[1]));
      }
    };
    const subscription = Linking.addEventListener("url", handleUrl);
    void Linking.getInitialURL().then(url => { if (url) handleUrl({ url }); }).catch(() => undefined);
    return () => subscription.remove();
  }, [token]);
  useEffect(() => {
    if (!token) return;
    void loadNotifications();
    const refreshVisibleScreen = async () => {
      if (AppState.currentState !== "active") return;
      const requestedScreen = screen;
      const requestedScope = scope;
      const feedGeneration = requestedScreen === "feed" ? feedRequestRef.current : null;
      const pollId = requestedScreen === "feed" ? ++feedPollRef.current : null;
      try {
        const [activityData, meData] = await Promise.all([request("/api/notifications"), request("/api/me")]);
        if (screenRef.current !== requestedScreen || scopeRef.current !== requestedScope) return;
        if (feedGeneration !== null && (feedGeneration !== feedRequestRef.current || pollId !== feedPollRef.current)) return;
        setUnreadNotifications(activityData.unread_count);
        setActivityCounts(meData.user.activity_counts || null);
        if (screen === "feed") {
          const incoming = (await request(`/api/feed?scope=${requestedScope}`)).posts as Post[];
          if (feedGeneration !== feedRequestRef.current || pollId !== feedPollRef.current
            || screenRef.current !== "feed" || scopeRef.current !== requestedScope) return;
          if (JSON.stringify(postsRef.current) === JSON.stringify(incoming)) return;
          const anchor = feedScrollYRef.current > 0
            ? feedInsertionAnchor(postsRef.current, incoming, feedPostPositionsRef.current) : null;
          pendingFeedAnchorRef.current = anchor ? { ...anchor, scope: requestedScope } : null;
          postsRef.current = incoming;
          setPosts(incoming);
        } else if (screen === "notifications") {
          setNotifications(activityData.notifications);
        } else if (screen === "inbox") {
          setConversations((await request("/api/conversations")).conversations);
        } else if (screen === "messages" && conversationId !== null) {
          await refreshConversationMessages(conversationId);
        }
      } catch (e) { fail(e); }
    };
    const stateSubscription = AppState.addEventListener("change", state => {
      if (state === "active") {
        refreshVisibleScreen();
        if (pushRetryPendingRef.current && !pushReturnRetryUsedRef.current) {
          pushReturnRetryUsedRef.current = true;
          pushRetryPendingRef.current = false;
          void registerPushToken(token).then(enabled => {
            if (enabled === true) setError(current => current === pushRegistrationErrorMessage({ code: "SERVICE_NOT_AVAILABLE" }) ? "" : current);
          }).catch(error => {
            if (isTransientPushServiceUnavailable(error)) setError(pushRegistrationErrorMessage(error));
            else fail(error);
          });
        }
      }
    });
    const interval = setInterval(refreshVisibleScreen, 20000);
    return () => {
      clearInterval(interval);
      stateSubscription.remove();
    };
  }, [token, screen, scope, conversationId, posts]);
  useEffect(() => {
    if (!token) { setBlockedUsers([]); setBlockedUsersLoaded(false); return; }
    let active = true;
    setBlockedUsersLoaded(false);
    void request("/api/blocks").then(result => {
      if (active) { setBlockedUsers(result.users || []); setBlockedUsersLoaded(true); }
    }).catch(error => { if (active) fail(error); });
    return () => { active = false; };
  }, [token]);
  useEffect(() => {
    const requestId = ++mentionRequestRef.current;
    if (!token || !blockedUsersLoaded || !mentionTarget?.query) {
      setMentionSuggestions([]);
      setMentionSuggestionsLoading(false);
      return;
    }
    setMentionSuggestionsLoading(true);
    const timer = setTimeout(async () => {
      try {
        const result = await request(`/api/search?q=${encodeURIComponent(mentionTarget.query)}`);
        if (requestId !== mentionRequestRef.current) return;
        const blocked = new Set(blockedUsers.map(person => person.username.toLowerCase()));
        setMentionSuggestions((result.people || []).filter((person: Member) => !blocked.has(person.username.toLowerCase())));
      } catch (e) {
        if (requestId === mentionRequestRef.current) { setMentionSuggestions([]); fail(e); }
      } finally {
        if (requestId === mentionRequestRef.current) setMentionSuggestionsLoading(false);
      }
    }, 280);
    return () => clearTimeout(timer);
  }, [token, blockedUsersLoaded, mentionTarget?.key, mentionTarget?.query, blockedUsers]);
  useEffect(() => {
    const requestId = ++inboxSearchRequestRef.current;
    const query = (form.recipient || "").trim();
    if (screen !== "inbox" || !token || !blockedUsersLoaded || !query) {
      setInboxSearchResults([]);
      return;
    }
    setInboxSearchResults([]);
    const timer = setTimeout(async () => {
      try {
        const result = await request(`/api/search?q=${encodeURIComponent(query)}`);
        if (requestId !== inboxSearchRequestRef.current || screenRef.current !== "inbox"
          || (form.recipient || "").trim() !== query) return;
        const blocked = new Set(blockedUsers.map(person => person.username.toLowerCase()));
        setInboxSearchResults((result.people || []).filter((person: Member) => !blocked.has(person.username.toLowerCase())));
      } catch (e) {
        if (requestId === inboxSearchRequestRef.current) fail(e);
      }
    }, 280);
    return () => clearTimeout(timer);
  }, [screen, token, form.recipient, blockedUsersLoaded, blockedUsers]);
  useEffect(() => {
    const requestId = ++searchRequestRef.current;
    if (screen !== "explore" || !blockedUsersLoaded) return;
    const query = (form.query || "").trim();
    if (!query) { setSearch(null); return; }
    setSearch(null);
    const timer = setTimeout(async () => {
      try {
        const result = await request(`/api/search?q=${encodeURIComponent(query)}`);
        if (requestId !== searchRequestRef.current) return;
        const blocked = new Set(blockedUsers.map(person => person.username.toLowerCase()));
        setSearch({ ...result, people: (result.people || []).filter((person: Member) => !blocked.has(person.username.toLowerCase())) });
      } catch (e) { if (requestId === searchRequestRef.current) fail(e); }
    }, 300);
    return () => clearTimeout(timer);
  }, [screen, form.query, token, blockedUsersLoaded, blockedUsers]);
  async function runAuthAction(action: () => Promise<void>) {
    if (authSubmissionRef.current) return;
    authSubmissionRef.current = true;
    setLoading(true);
    try { await action(); }
    catch (e) { fail(e); }
    finally { authSubmissionRef.current = false; setLoading(false); }
  }
  async function submitAuth(register = false) {
    if (register) {
      if (form.accept_terms !== "true") { setError("Confirm that you are 18 or older and accept the Terms of Use and Privacy Policy."); return; }
      const issue = passwordPolicyError(form.password || "");
      if (issue) { setError(issue); return; }
    }
    await runAuthAction(async () => {
      if (register) {
        const result = await request("/api/auth/register", "POST", {
          email: (form.email || "").trim().toLowerCase(),
          password: form.password,
          accept_terms: true,
        });
        const email = (form.email || "").trim().toLowerCase();
        setSignupEmail(email);
        setForm(current => ({ ...current, email, password: "", code: "" }));
        setScreen("verify-register");
        setError(result.message);
      } else {
        const data = await request("/api/auth/login", "POST", form);
        await enterApp(data.token);
      }
    });
  }
  async function verifyRegistration() {
    await runAuthAction(async () => {
      const data = await request("/api/auth/register/verify", "POST", {
        email: signupEmail, code: form.code,
      });
      await enterApp(data.token);
    });
  }
  async function logout() {
    pushSessionGenerationRef.current++;
    pushSessionRef.current = "";
    pushRetryPendingRef.current = false;
    pushReturnRetryUsedRef.current = false;
    const postingRegistration = pushPostingRef.current ? pushRegistrationPromiseRef.current : null;
    const registeredPushToken = pushTokenRef.current;
    pushTokenRef.current = null;
    if (postingRegistration) {
      if (!await waitForPushCleanup(postingRegistration)) warnPushCleanup();
    }
    if (registeredPushToken) {
      if (!await waitForPushCleanup(request("/api/push-token", "DELETE", { token: registeredPushToken, platform: Platform.OS }))) warnPushCleanup();
    }
    try { await request("/api/auth/logout", "POST"); }
    catch (e) { fail(e); }
    await SecureStore.deleteItemAsync("zorlii_session");
    resetConversationState();
    setToken(""); updateMe(null); setScreen("login"); setForm({}); setPostMedia([]);
  }
  async function exportAccount() {
    try {
      const data = await request("/api/account/export");
      await Share.share({
        title: "Zorlii account data",
        message: JSON.stringify(data, null, 2),
      });
    } catch (e) { fail(e); }
  }
  function confirmAccountDeletion() {
    if (form.delete_confirmation !== me?.username) {
      setError("Enter your exact username to confirm account deletion.");
      return;
    }
    Alert.alert(
      "Permanently delete your account?",
      "Your profile and account-owned content will be deleted. This cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Delete account", style: "destructive", onPress: async () => {
          setLoading(true);
          try {
            await request("/api/account", "DELETE", { password: form.delete_password || "" });
            pushSessionGenerationRef.current++;
            pushSessionRef.current = "";
            pushTokenRef.current = null;
            pushRetryPendingRef.current = false;
            await SecureStore.deleteItemAsync("zorlii_session");
            resetConversationState();
            setToken(""); updateMe(null); setForm({}); setPostMedia([]); setScreen("login");
            setError("Your account and account-owned content have been deleted.");
          } catch (e) { fail(e); }
          finally { setLoading(false); }
        } },
      ],
    );
  }
  async function togglePost(post: Post, action: "reaction" | "bookmark" | "repost") {
    try {
      await request(`/api/posts/${post.id}/${action}`, "POST");
      const result = await request(`/api/posts/${post.id}`);
      replacePostEverywhere(result.post);
      if (screen === "thread") setThreadPost(result.post);
      else if (screen === "feed") await loadFeed();
    }
    catch (e) { fail(e); }
  }
  async function toggleReply(reply: Reply, action: "reaction" | "repost") {
    try {
      await request(`/api/replies/${reply.id}/${action}`, "POST");
      const property = action === "reaction" ? "reacted" : "reposted";
      const count = action === "reaction" ? "reaction_count" : "repost_count";
      setThreadReplies(current => current.map(item => item.id === reply.id
        ? { ...item, [property]: !item[property], [count]: Math.max(0, item[count] + (item[property] ? -1 : 1)) } : item));
    } catch (e) { fail(e); }
  }
  function showEchoOptions(item: Post | Reply, type: "post" | "reply") {
    setEchoTarget({ item, type });
  }
  function chooseEcho(option: "echo" | "thought") {
    const target = echoTarget;
    setEchoTarget(null);
    if (!target) return;
    if (option === "thought") {
      quote(target.item, target.type);
    } else if (target.type === "post") {
      void togglePost(target.item as Post, "repost");
    } else {
      void toggleReply(target.item as Reply, "repost");
    }
  }
  function quote(item: Post | Reply, type: "post" | "reply") {
    setQuoteTarget({ item, type });
    if (screen !== "feed") {
      setScreen("feed");
      void loadFeed();
    }
    requestAnimationFrame(() => composerRef.current?.focus());
  }
  async function sendReply(post: Post) {
    const bodyText = (form[`reply-${post.id}`] || "").trim();
    const replyMedia = replyMediaByPost[post.id] || [];
    if (!bodyText && !replyMedia.length) { setError("Write a reply or add media before sending."); return; }
    if (replySubmissionRef.current.has(post.id)) return;
    replySubmissionRef.current.add(post.id);
    let replyCreated = false;
    try {
      if (replyMedia.length) {
        const body = new FormData() as NativeUploadFormData;
        body.append("body", bodyText);
        replyMedia.forEach((asset, index) => {
          const type = asset.mimeType?.toLowerCase() || "application/octet-stream";
          body.append("media", {
            uri: asset.uri,
            name: nativeUploadName(asset.fileName, `reply-${index}`, type),
            type,
          });
        });
        await uploadRequest(`/api/posts/${post.id}/replies/media`, body);
      } else {
        await request(`/api/posts/${post.id}/replies`, "POST", { body: bodyText });
      }
      replyCreated = true;
      update(`reply-${post.id}`, "");
      setReplyMediaByPost(current => { const next = { ...current }; delete next[post.id]; return next; });
      if (screen === "thread" && threadPost?.id === post.id) await refreshThread();
      else {
        const result = await request(`/api/posts/${post.id}`);
        setReplies(current => ({ ...current, [post.id]: result.replies }));
      }
    }
    catch (e) {
      if (replyCreated && screen === "thread" && threadPost?.id === post.id) {
        setThreadError(`Reply sent, but the thread could not be refreshed: ${e instanceof Error ? e.message : "Please try again."}`);
      } else fail(e);
    }
    finally { replySubmissionRef.current.delete(post.id); }
  }
  function contentText(item: Post | Reply) {
    const body = item.body?.trim() || "";
    return `${body}${body ? "\n\n" : ""}— ${item.author.display_name || item.author.username} (@${item.author.username})`;
  }
  async function copyContent(item: Post | Reply) {
    try {
      if (!await Clipboard.setStringAsync(contentText(item))) throw new Error("Clipboard access failed.");
      setContentMenu(null);
      Alert.alert("Copied", "The content and author attribution were copied to your clipboard.");
    } catch (e) { fail(e); }
  }
  async function shareContent(item: Post | Reply, type: "post" | "reply") {
    try {
      await Share.share({ title: `Zorlii ${type} by ${item.author.display_name || item.author.username}`, message: contentText(item) });
      setContentMenu(null);
    } catch (e) { fail(e); }
  }
  function beginEditContent(target: ContentTarget) {
    if (!me || target.item.author.id !== me.id) return;
    setContentMenu(null);
    setEditingBody(target.item.body || "");
    setEditingContent(target);
    setError("");
  }
  async function saveEditedContent() {
    const target = editingContent;
    if (!target || !me || target.item.author.id !== me.id) return;
    const body = editingBody;
    const item = target.item;
    if (!body.trim() && !item.media?.length && !item.quoted_post && !item.quoted_reply) {
      setError("Add text, media, or an original before saving.");
      return;
    }
    try {
      const result = await request(`/api/${target.type === "post" ? "posts" : "replies"}/${item.id}`, "PATCH", { body });
      feedRequestRef.current++;
      feedPollRef.current++;
      if (screenRef.current === "feed") setLoading(false);
      if (target.type === "post") replacePostEverywhere(result.post as Post);
      else setReplies(current => Object.fromEntries(Object.entries(current).map(([postId, items]) => [
        postId, items.map((reply: Reply) => reply.id === item.id ? result as Reply : reply),
      ])));
      setEditingContent(null);
      setEditingBody("");
      Alert.alert("Saved", "Your changes were saved.");
    } catch (e) { fail(e); }
  }
  function confirmDeleteContent(target: ContentTarget) {
    if (!me || target.item.author.id !== me.id) return;
    const warning = target.type === "reply"
      ? "This permanently deletes the reply and may also remove reposts of it and replies to those reposts."
      : "This permanently deletes the post, its replies and its uploaded media.";
    Alert.alert(`Delete this ${target.type}?`, warning, [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => {
        try {
          await request(`/api/${target.type === "post" ? "posts" : "replies"}/${target.item.id}`, "DELETE");
          feedRequestRef.current++;
          feedPollRef.current++;
          if (screenRef.current === "feed") setLoading(false);
          if (target.type === "post") removePostEverywhere(target.item.id);
          else {
            const dependentPostIds = new Set([
              ...postsRef.current, ...profilePosts, ...publicProfilePosts, ...hashtagPosts,
              ...((search?.posts || []) as Post[]),
            ].filter(post => post.reposted_reply && post.quoted_reply?.id === target.item.id).map(post => post.id));
            const clearQuotes = (items: Post[]) => postsAfterReplyDeletion(items, target.item.id);
            postsRef.current = clearQuotes(postsRef.current);
            setPosts(postsRef.current);
            setProfilePosts(clearQuotes);
            setPublicProfilePosts(clearQuotes);
            setHashtagPosts(clearQuotes);
            setSearch((current: any) => current ? { ...current, posts: clearQuotes(current.posts || []) } : current);
            setReplies(current => {
              const next = Object.fromEntries(Object.entries(current).map(([postId, items]) => [
                postId, items.filter((reply: Reply) => reply.id !== target.item.id)
                  .map((reply: Reply) => reply.quoted_reply?.id === target.item.id ? { ...reply, quoted_reply: null } : reply),
              ])) as Record<number, Reply[]>;
              dependentPostIds.forEach(postId => { delete next[postId]; });
              return next;
            });
            if (target.parentPostId) {
              const decrement = (items: Post[]) => items.map(post => post.id === target.parentPostId
                ? { ...post, reply_count: Math.max(0, post.reply_count - 1) } : post);
              postsRef.current = decrement(postsRef.current);
              setPosts(postsRef.current);
              setProfilePosts(decrement);
              setPublicProfilePosts(decrement);
              setHashtagPosts(decrement);
              setSearch((current: any) => current ? { ...current, posts: decrement(current.posts || []) } : current);
            }
          }
          setContentMenu(null);
          Alert.alert("Deleted", `${target.type === "post" ? "Post" : "Reply"} deleted.`);
        } catch (e) { fail(e); }
      } },
    ]);
  }
  async function startConversation(username: string) {
    try { const data = await request("/api/conversations", "POST", { username }); await loadInbox(); await loadConversation(data.id); }
    catch (e) { fail(e); }
  }
  async function searchInboxMembers() {
    const query = (form.recipient || "").trim();
    if (!query) { setError("Enter a username to find a member."); return; }
    const requestId = ++inboxSearchRequestRef.current;
    try {
      const result = await request(`/api/search?q=${encodeURIComponent(query)}`);
      if (requestId !== inboxSearchRequestRef.current || screenRef.current !== "inbox" || (form.recipient || "").trim() !== query) return;
      const blocked = new Set(blockedUsers.map(person => person.username.toLowerCase()));
      setInboxSearchResults((result.people || []).filter((person: Member) => !blocked.has(person.username.toLowerCase())));
    } catch (e) { if (requestId === inboxSearchRequestRef.current) fail(e); }
  }
  async function sharePost() {
    if (quoteTarget && !(form.post || "").trim()) {
      setError("Add a thought before Echoing the original.");
      return;
    }
    if (!(form.post || "").trim() && !postMedia.length && !quoteTarget) {
      setError("Write a thought, add media, or include an original before sharing.");
      return;
    }
    if (postSubmissionRef.current) return;
    postSubmissionRef.current = true;
    setLoading(true);
    try {
      const quoteFields = quoteTarget ? {
        [quoteTarget.type === "post" ? "quoted_post_id" : "quoted_reply_id"]: quoteTarget.item.id,
      } : {};
      if (postMedia.length) {
        const body = new FormData() as NativeUploadFormData;
        body.append("body", form.post || "");
        body.append("visibility", form.visibility || "public");
        Object.entries(quoteFields).forEach(([key, value]) => body.append(key, String(value)));
        postMedia.forEach((asset, index) => {
          const type = asset.mimeType?.toLowerCase() || "application/octet-stream";
          body.append("media", {
            uri: asset.uri,
            name: nativeUploadName(asset.fileName, `media-${index}`, type),
            type,
          });
        });
        await uploadRequest("/api/posts/media", body);
      } else {
        await request("/api/posts", "POST", { body: form.post, visibility: form.visibility || "public", ...quoteFields });
      }
      setPostMedia([]);
      setQuoteTarget(null);
      update("post", "");
      await loadFeed();
    } catch (e) { fail(e); }
    finally { setLoading(false); postSubmissionRef.current = false; }
  }

  const field = (name: string, placeholder: string, secure = false, multiline = false, visibleLabel?: string) => {
    const profileValue = name === "display_name" ? me?.display_name
      : name === "username" ? me?.username
      : name === "bio" ? me?.bio : name === "interests" ? me?.interests.join(", ") : undefined;
    const isPasswordVisible = Boolean(visiblePasswords[name]);
    return (
    <View style={visibleLabel ? [styles.authField, compactAuth && styles.authFieldCompact] : undefined}>
      {visibleLabel ? <Text style={styles.authFieldLabel}>{visibleLabel}</Text> : null}
      <View style={secure && styles.passwordFieldRow}>
        <TextInput accessibilityLabel={visibleLabel || placeholder} placeholder={visibleLabel ? "" : placeholder} placeholderTextColor={palette.muted}
          value={form[name] ?? profileValue ?? ""} onChangeText={value => update(name, name === "username" ? value.toLowerCase() : value)} secureTextEntry={secure && !isPasswordVisible}
          multiline={multiline} keyboardType={name === "code" ? "number-pad" : "default"}
          maxLength={name === "code" ? 6 : name === "password" && (screen === "register" || screen === "reset-code") ? 128 : name === "username" ? 24 : undefined}
          autoCapitalize="none" autoCorrect={name !== "username"} style={[styles.input, visibleLabel && styles.authInput, secure && styles.passwordInput, multiline && styles.multiline,
            visibleLabel
              ? { backgroundColor: mixColor(themeColor, "#0b0d1d", 0.14), borderColor: mixColor(safeAccent, "#282744", 0.32), color: "#f4f1ff" }
              : { backgroundColor: palette.input, borderColor: palette.border, color: "#f5f2ff" }]} />
        {secure ? <Pressable accessibilityRole="button"
          accessibilityLabel={`${isPasswordVisible ? "Hide" : "Show"} ${placeholder.toLowerCase()}`}
          accessibilityState={{ selected: isPasswordVisible }}
          onPress={() => setVisiblePasswords(current => ({ ...current, [name]: !current[name] }))}
          focusable style={visibleLabel ? styles.authPasswordToggle : [styles.passwordToggle, { borderColor: palette.border }]}>
          <Text style={[styles.passwordToggleText, visibleLabel && styles.authPasswordToggleText, visibleLabel && { color: safeAccent }]}>{isPasswordVisible ? "Hide" : "Show"}</Text></Pressable> : null}
      </View>
      {secure && (screen === "register" || screen === "reset-code") ? <View accessibilityLiveRegion="polite">
        {passwordRequirements(form[name] || "").map(requirement => <Text key={requirement.label}
          style={[styles.passwordRequirement, requirement.met && styles.passwordRequirementMet]}>
          {requirement.met ? "✓" : "○"} {requirement.label}
        </Text>)}
      </View> : null}
    </View>
    );
  };
  const savedThemeColor = validHexColor(me?.theme_color) ? me.theme_color : DEFAULT_ACCENT;
  const themeColor = screen === "settings" && validHexColor(themeColorDraft) ? themeColorDraft : savedThemeColor;
  const safeAccent = readableAccent(themeColor);
  const themeText = contrastForeground(safeAccent);
  const palette = {
    background: mixColor(themeColor, "#080a16", 0.18),
    surface: mixColor(themeColor, "#101329", 0.24),
    raised: mixColor(themeColor, "#17182e", 0.3),
    border: mixColor(themeColor, "#282744", 0.5),
    input: mixColor(themeColor, "#0b0d1d", 0.16),
    muted: "#e5e2ee",
  };
  const themedSurface = { backgroundColor: palette.surface, borderColor: palette.border };
  const themedRaised = { backgroundColor: palette.raised, borderColor: palette.border };
  activeThemeAccent = themeColor;
  const closeMenu = (afterClose?: () => void) => {
    if (!menuOpen || reduceMotion) {
      setMenuOpen(false);
      afterClose?.();
      return;
    }
    if (menuClosePendingRef.current) return;
    menuClosePendingRef.current = true;
    Animated.parallel([
      Animated.timing(menuTranslateX, { toValue: menuDrawerWidth, duration: 180, easing: Easing.in(Easing.quad), useNativeDriver: true }),
      Animated.timing(menuScrimOpacity, { toValue: 0, duration: 150, useNativeDriver: true }),
    ]).start(({ finished }) => {
      menuClosePendingRef.current = false;
      if (finished) {
        setMenuOpen(false);
        afterClose?.();
      }
    });
  };
  const button = (label: string, action: () => void, secondary = false) => (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={action} style={({ pressed }) => [styles.button, secondary && styles.secondary,
      secondary ? { borderColor: safeAccent, backgroundColor: palette.surface } : { backgroundColor: safeAccent, borderColor: safeAccent, shadowColor: safeAccent }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
      <Text style={[styles.buttonText, secondary ? { color: safeAccent } : { color: themeText }]}>{label}</Text>
    </Pressable>
  );
  const authAction = (label: string, action: () => void, primary = false, pendingLabel = "Please wait…") => {
    const disabled = loading || authSubmissionRef.current;
    return <Pressable accessibilityRole="button" accessibilityLabel={disabled && primary ? pendingLabel : label}
      accessibilityState={{ disabled, busy: disabled }} disabled={disabled} focusable onPress={action}
      style={({ pressed }) => [styles.authAction, primary && styles.authActionPrimary, disabled && styles.authActionDisabled,
        pressed && !disabled && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
      <Text style={[styles.authActionText, primary && styles.authActionPrimaryText, { color: safeAccent }]}>{disabled && primary ? pendingLabel : label}</Text>
      {primary ? disabled ? <ActivityIndicator size="small" color={safeAccent} /> : <Text style={[styles.authActionArrow, { color: safeAccent }]} accessibilityElementsHidden>→</Text> : null}
    </Pressable>;
  };
  const followButton = (person: Pick<Member, "username">) => {
    const key = person.username.toLowerCase(), following = followStates[key], busy = followBusyUsers.has(key);
    const label = following === undefined ? (followStatusErrors[key] ? "Follow status unavailable" : "Checking…")
      : busy ? "Updating…" : following ? "Following" : "Follow";
    return <Pressable accessibilityRole="button" accessibilityLabel={following === undefined
      ? `Follow status for @${person.username} is unavailable` : `${label} @${person.username}`}
      accessibilityState={{ disabled: following === undefined || busy, busy }}
      disabled={following === undefined || busy} onPress={() => { void toggleFollow(person.username); }}
      style={({ pressed }) => [styles.button, styles.secondary, { borderColor: safeAccent }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
      <Text style={[styles.buttonText, styles.secondaryText, { color: safeAccent }]}>{label}</Text>
    </Pressable>;
  };
  const menuButton = (label: string, action: () => void, badge?: number) => <Pressable accessibilityRole="button"
    accessibilityLabel={badge ? `${label}, ${badge} unread` : label}
    onPress={() => closeMenu(action)} style={({ pressed }) => [styles.menuItem, { backgroundColor: palette.surface, borderColor: palette.border }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
    <Text style={styles.menuItemText}>{label}</Text>
    {badge ? <View style={[styles.menuUnreadBadge, { backgroundColor: safeAccent }]}><Text style={[styles.menuUnreadText, { color: themeText }]}>{badge}</Text></View> : null}
  </Pressable>;
  const mentionPicker = (key: string) => mentionTarget?.key === key ? <View style={[styles.mentionSuggestions, { borderColor: palette.border }]}
    accessibilityLiveRegion="polite">
    {mentionSuggestionsLoading ? <Text style={styles.handle}>Finding members…</Text> : mentionSuggestions.length
      ? mentionSuggestions.map(person => <Pressable key={person.id} accessibilityRole="button"
        accessibilityLabel={`Mention @${person.username}`} onPress={() => selectMention(person)} style={styles.mentionSuggestion}>
        <Avatar user={person} size={30} />
        <Text style={styles.author}>{person.display_name}</Text>
        <Text style={styles.handle}>@{person.username}</Text>
      </Pressable>)
      : <Text style={styles.handle}>No matching accounts.</Text>}
  </View> : null;
  const disclosure = (key: string, label: string, content: React.ReactNode) => {
    const expanded = Boolean(profileSections[key]);
    return <View style={[styles.disclosure, { backgroundColor: palette.surface, borderColor: palette.border }]}>
      <Pressable accessibilityRole="button" accessibilityState={{ expanded }}
        onPress={() => setProfileSections(current => ({ ...current, [key]: !current[key] }))}
        style={styles.disclosureTrigger}>
        <Text style={styles.disclosureTitle}>{label}</Text>
          <Text style={[styles.disclosureIcon, { color: safeAccent }]} accessibilityElementsHidden>{expanded ? "−" : "+"}</Text>
      </Pressable>
      {expanded ? <View style={styles.disclosureContent}>{content}</View> : null}
    </View>;
  };
  const socialAction = (label: string, icon: SocialIconName, count: number | undefined, action: () => void, selected = false, color?: string) => (
    <Pressable accessibilityRole="button" accessibilityLabel={count === undefined ? label : `${label}, ${count}`}
      accessibilityState={{ selected }} onPress={action}
      style={({ pressed }) => [styles.socialAction, selected && styles.socialActionSelected,
        pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
      <SocialActionIcon name={icon} selected={selected} color={color || (selected ? safeAccent : palette.muted)} />
      {count !== undefined ? <Text accessibilityElementsHidden style={[styles.socialActionCount, { color: palette.muted }]}>{count}</Text> : null}
    </Pressable>
  );
  const echoButton = (item: Post | Reply, type: "post" | "reply") => (
    <Pressable accessibilityRole="button"
      accessibilityLabel={`Echo options${item.repost_count ? `, ${item.repost_count} echoes` : ""}`}
      accessibilityHint="Choose Echo or Echo with a thought."
      accessibilityState={{ selected: item.reposted }}
      onPress={() => showEchoOptions(item, type)}
      style={({ pressed }) => [styles.socialAction, item.reposted && styles.socialActionSelected,
        pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
      <SocialActionIcon name="repost" selected={item.reposted} color={item.reposted ? safeAccent : palette.muted} />
      {item.repost_count ? <Text accessibilityElementsHidden style={[styles.socialActionCount, { color: palette.muted }]}>{item.repost_count}</Text> : null}
    </Pressable>
  );
  const profileLink = (username: string, label: string, textStyle: any = styles.author) => (
    <Text accessibilityRole="link" accessibilityLabel={`View @${username}'s profile`}
      onPress={() => { void openPublicProfile(username); }} style={[textStyle, styles.profileLink, { color: readableAccent(activeThemeAccent) }]}>{label}</Text>
  );
  const profilePhotoAction = (user?: { display_name?: string; username?: string; avatar_url?: string | null } | null) =>
    user?.avatar_url ? () => showImage(`${API_URL}${user.avatar_url}`, `${user.display_name || user.username || "Member"} profile photo`) : undefined;
  const navItems = ["feed", "explore", "create", "inbox", "profile"];
  const navLabels: Record<string, string> = {
    feed: "Pulse", explore: "Explore", create: "Create", inbox: "Inbox", profile: "Profile",
  };
  const navIcons: Record<string, string> = {
    feed: "⌂", explore: "⌕", create: "+", inbox: "✉", profile: "♙",
  };
  const nav = () => <View style={[styles.tabs, { backgroundColor: palette.surface, borderTopColor: palette.border }]} accessibilityLabel="Main navigation">
    {navItems.map(item => {
      const selected = screen.startsWith(item) || (item === "profile" && (screen.startsWith("social-") || screen === "blocked" || screen === "public-profile"))
        || (item === "inbox" && screen === "messages");
      const label = item === "create" ? "Create a post" : navLabels[item];
      return <Pressable key={item} accessibilityRole="button" accessibilityLabel={label}
        accessibilityState={{ selected }} style={({ pressed }) => [styles.tabItem, item === "create" && styles.createTab, pressed && styles.tabPressed]}
        onPress={() => {
          if (item === "feed") { setScreen("feed"); loadFeed(); }
          if (item === "explore") setScreen("explore");
          if (item === "create") {
            if (screen !== "feed") { setScreen("feed"); loadFeed(); }
            requestAnimationFrame(() => composerRef.current?.focus());
          }
          if (item === "inbox") loadInbox();
          if (item === "profile") loadProfile();
        }}>
        <Text style={[styles.tabIcon, { color: selected ? safeAccent : palette.muted }, selected && styles.activeTabIcon, item === "create" && styles.createIcon,
          item === "create" && { backgroundColor: safeAccent, color: themeText }]}
          accessibilityElementsHidden>{navIcons[item]}</Text>
        <Text style={[styles.tab, { color: selected ? safeAccent : palette.muted }, selected && styles.activeTab]}>{navLabels[item]}</Text>
      </Pressable>;
    })}
  </View>;
  const mediaContent = (media?: PostMedia[]) => {
    if (!media?.length) return null;
    const multiple = media.length > 1;
    return <View style={multiple ? styles.mediaGrid : undefined}>
      {media.map((item, index) => item.media_type.startsWith("video/")
        ? <PostVideo key={item.id} uri={`${API_URL}${item.url}`} token={token}
            style={multiple ? styles.gridVideo : styles.postVideo} />
        : <Pressable key={item.id} accessibilityRole="button"
            accessibilityLabel={`View photo ${index + 1} of ${media.length} larger`}
            onPress={() => showImage(`${API_URL}${item.url}`, `Post photo ${index + 1}`)}
            style={multiple ? styles.mediaTile : styles.singleMedia}>
            <Image source={{ uri: `${API_URL}${item.url}`, headers: { Authorization: `Bearer ${token}` } }}
              style={styles.postImage} resizeMode="cover" />
          </Pressable>)}
    </View>;
  };
  async function openQuotedThread(item: Post | Reply, kind: string) {
    if (kind === "post") {
      await openThread(item as Post);
      return;
    }
    const postId = (item as Reply).post_id;
    if (!postId) {
      fail(new Error("This quoted reply’s thread is unavailable."));
      return;
    }
    try {
      const result = await request(`/api/posts/${postId}`);
      await openThread(result.post, item.id);
    } catch (e) { fail(e); }
  }
  const quotedContent = (item?: Post | Reply | null, kind = "post") => item ? <View style={[styles.quotedItem, themedSurface]}>
    <Pressable accessibilityRole="button" accessibilityLabel={`Open thread for quoted ${kind} by @${item.author.username}`}
      onPress={() => { void openQuotedThread(item, kind); }} style={styles.quotedOpen}>
      <Text style={[styles.quotedLabel, { color: safeAccent }]}>Open quoted {kind} thread</Text>
      {item.body ? <Text style={styles.postBody} numberOfLines={4}>{taggedText(item.body)}</Text> : <Text style={styles.copy}>View the original conversation.</Text>}
    </Pressable>
    <View style={styles.postAuthor}><Avatar user={item.author} size={30} onPress={profilePhotoAction(item.author)} /><View>
      {profileLink(item.author.username, item.author.display_name)}
      {profileLink(item.author.username, `@${item.author.username}`, styles.handle)}
    </View></View>
    {mediaContent(item.media)}
  </View> : null;
  const contentMenuButton = (label: string, action: () => void, destructive = false) => <Pressable
    accessibilityRole="button" onPress={action} style={({ pressed }) => [styles.contentMenuButton,
      { borderColor: destructive ? "#b96882" : palette.border },
      pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
    <Text style={[styles.contentMenuLabel, destructive && styles.contentMenuDestructive]}>{label}</Text>
  </Pressable>;
  const contentMenuControl = (item: Post | Reply, type: "post" | "reply", parentPostId?: number) => {
    const isOwner = item.author.id === me?.id;
    const isOpen = contentMenu?.type === type && contentMenu.id === item.id;
    const menuKey = `${type}-${item.id}`;
    const target: ContentTarget = { type, item, parentPostId };
    return <View style={styles.contentMenuAnchor}>
      <Pressable ref={node => { contentMenuAnchorsRef.current[menuKey] = node; }}
        accessibilityRole="button" accessibilityLabel={`${type === "post" ? "Post" : "Reply"} options`}
        accessibilityState={{ expanded: isOpen }} accessibilityHint="Copy, share, edit, delete, or view safety actions."
        onPress={() => {
          if (isOpen) { setContentMenu(null); return; }
          const anchor = contentMenuAnchorsRef.current[menuKey];
          anchor?.measureInWindow((_x, y, _width, height) => {
            const menuHeight = isOwner ? 184 : 228;
            setContentMenuPlacement(y + height + menuHeight > windowHeight - insets.bottom - 8 ? "above" : "below");
          });
          setContentMenu({ type, id: item.id });
        }}
        style={({ pressed }) => [styles.contentMenuTrigger, { borderColor: palette.border }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
        <Text style={[styles.contentMenuDots, { color: safeAccent }]} accessibilityElementsHidden>•••</Text>
      </Pressable>
      {isOpen ? <View style={[styles.contentMenu, contentMenuPlacement === "above" ? styles.contentMenuAbove : styles.contentMenuBelow,
        { backgroundColor: palette.surface, borderColor: palette.border }]} accessibilityRole="menu">
        {contentMenuButton("Copy", () => { void copyContent(item); })}
        {contentMenuButton("Share", () => { void shareContent(item, type); })}
        {isOwner ? <>
          {contentMenuButton("Edit", () => beginEditContent(target))}
          {contentMenuButton("Delete", () => confirmDeleteContent(target), true)}
        </> : contentMenuButton("Safety options", () => {
          setContentMenu(null);
          showSafetyOptions(item.author, type === "post" ? item as Post : undefined);
        })}
      </View> : null}
    </View>;
  };
  const replyCard = (reply: Reply, parentPostId: number) => <View key={reply.id} style={[styles.replyCard, { backgroundColor: palette.surface, borderColor: palette.border },
    contentMenu?.type === "reply" && contentMenu.id === reply.id && styles.contentMenuActiveCard]}>
    <View style={[styles.postAuthor, contentMenu?.type === "reply" && contentMenu.id === reply.id && styles.contentMenuActiveRow]}>{contentMenuControl(reply, "reply", parentPostId)}<Avatar user={reply.author} size={36} onPress={profilePhotoAction(reply.author)} /><View style={{ flex: 1 }}>
      {profileLink(reply.author.username, reply.author.display_name)}
      {profileLink(reply.author.username, `@${reply.author.username}`, styles.handle)}
    </View></View>
    {reply.body ? <Text style={styles.postBody}>{taggedText(reply.body)}</Text> : null}
    {mediaContent(reply.media)}
    {reply.quoted_post ? quotedContent(reply.quoted_post, "post") : null}
    {reply.quoted_reply ? quotedContent(reply.quoted_reply, "reply") : null}
    <View style={styles.actions}>
      {socialAction(reply.reacted ? "Unlike reply" : "Like reply", "heart", reply.reaction_count ?? 0,
        () => toggleReply(reply, "reaction"), reply.reacted, reply.reacted ? "#ff4f73" : undefined)}
      {echoButton(reply, "reply")}
      {button("Safety", () => showSafetyOptions(reply.author), true)}
    </View>
  </View>;
  const postCard = (post: Post) => <View key={post.id} onLayout={event => {
    if (screenRef.current !== "feed" || scopeRef.current !== scope) return;
    const top = event.nativeEvent.layout.y;
    feedPostPositionsRef.current[post.id] = top;
    const pending = pendingFeedAnchorRef.current;
    if (!pending || pending.id !== post.id) return;
    pendingFeedAnchorRef.current = null;
    if (pending.scope !== scopeRef.current || feedScrollYRef.current <= 0 || top === pending.top) return;
    const nextOffset = Math.max(0, feedScrollYRef.current + top - pending.top);
    requestAnimationFrame(() => {
      if (screenRef.current !== "feed" || scopeRef.current !== pending.scope) return;
      feedScrollRef.current?.scrollTo({ y: nextOffset, animated: false });
      feedScrollYRef.current = nextOffset;
    });
  }} style={[styles.post, styles.pulsePost, { backgroundColor: "transparent", borderColor: palette.border },
    ((contentMenu?.type === "post" && contentMenu.id === post.id) ||
      (contentMenu?.type === "reply" && replies[post.id]?.some(reply => reply.id === contentMenu.id))) && styles.contentMenuActiveCard]}>
    <View pointerEvents="none" style={[styles.pulseNode, { borderColor: safeAccent, backgroundColor: palette.background }]} />
    {post.reposted_by ? <Text style={[styles.repostLabel, { color: safeAccent }]}>↗  Echoed by @{post.reposted_by.username}</Text> : null}
    <View style={[styles.postAuthor, contentMenu?.type === "post" && contentMenu.id === post.id && styles.contentMenuActiveRow]}>{contentMenuControl(post, "post")}<Avatar user={post.author} onPress={profilePhotoAction(post.author)} /><View style={{ flex: 1 }}>
      {profileLink(post.author.username, post.author.display_name)}
      {profileLink(post.author.username, `@${post.author.username}`, styles.handle)}
    </View></View>
    {post.body ? <Pressable accessibilityRole="button" accessibilityLabel={`Open thread for @${post.author.username}`}
      onPress={() => { if (screen === "thread") composerInputRefs.current[`reply-${post.id}`]?.focus(); else void openThread(post); }}>
      <Text style={styles.postBody}>{taggedText(post.body)}</Text>
    </Pressable> : null}
    {mediaContent(post.media)}
    {post.quoted_post ? quotedContent(post.quoted_post, "post") : null}
    {post.quoted_reply ? quotedContent(post.quoted_reply, "reply") : null}
    <View style={styles.actions}>
      {socialAction(post.reacted ? "Unlike post" : "Like post", "heart", post.reaction_count,
        () => togglePost(post, "reaction"), post.reacted, post.reacted ? "#ff4f73" : undefined)}
      {echoButton(post, "post")}
      {socialAction("Open thread", "reply", post.reply_count, () => {
        if (screen === "thread") composerInputRefs.current[`reply-${post.id}`]?.focus();
        else void openThread(post);
      })}
      {socialAction(post.bookmarked ? "Remove saved post" : "Save post", "bookmark", undefined,
        () => togglePost(post, "bookmark"), post.bookmarked)}
      {button("Safety", () => showSafetyOptions(post.author, post), true)}
      {me?.is_moderator ? button("Remove post", () => removeModeratedPost(post), true) : null}
    </View>
  </View>;
  const threadComposer = (post: Post) => {
    const selectedMedia = replyMediaByPost[post.id] || [];
    return <View>
      <View style={[styles.composerRow, { borderColor: palette.border, backgroundColor: palette.input }]}>
        <TextInput ref={input => { composerInputRefs.current[`reply-${post.id}`] = input; }}
          accessibilityLabel="Write a thoughtful reply" placeholder="Write a reply…" placeholderTextColor={palette.muted}
          value={form[`reply-${post.id}`] || ""} onChangeText={value => updateComposerText(`reply-${post.id}`, value)}
          onSelectionChange={event => updateComposerSelection(`reply-${post.id}`, form[`reply-${post.id}`] || "", event.nativeEvent.selection)}
          selection={composerSelections[`reply-${post.id}`]} returnKeyType="send" onSubmitEditing={() => { void sendReply(post); }}
          style={[styles.replyInput, { color: "#f5f2ff" }]} />
        <MediaPickerButton label="Attach photos, videos, or GIFs to reply" onPress={() => pickPostMedia(post.id)} />
        <Pressable accessibilityRole="button" accessibilityLabel="Send reply" accessibilityHint="Send this reply."
          onPress={() => { void sendReply(post); }} style={({ pressed }) => [styles.arrowSubmit, { backgroundColor: safeAccent }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
          <Text style={[styles.arrowSubmitText, { color: themeText }]} accessibilityElementsHidden>➤</Text>
        </Pressable>
      </View>
      {mentionPicker(`reply-${post.id}`)}
      {selectedMedia.length ? button("Clear media", () => setReplyMediaByPost(current => { const next = { ...current }; delete next[post.id]; return next; }), true) : null}
      {selectedMedia.length ? <ScrollView horizontal style={styles.mediaSelection} contentContainerStyle={styles.mediaSelectionContent}>
        {selectedMedia.map((asset, index) => <View key={`${asset.assetId || asset.uri}-${index}`} style={styles.mediaSelectionItem}>
          {asset.type === "video" ? <Text style={styles.mediaSelectionText}>Video</Text> : <Image source={{ uri: asset.uri }} style={styles.mediaSelectionImage} />}
          <Pressable accessibilityRole="button" accessibilityLabel={`Remove selected reply media ${index + 1}`} style={styles.mediaRemove}
            onPress={() => setReplyMediaByPost(current => ({ ...current, [post.id]: (current[post.id] || []).filter((_, itemIndex) => itemIndex !== index) }))}>
            <Text style={styles.mediaRemoveText}>×</Text>
          </Pressable>
        </View>)}
      </ScrollView> : null}
    </View>;
  };

  function renderBody() {
    const authJourney = (title: string, description: string, children: React.ReactNode) => <>
      <View style={styles.authIntro}>
        <View style={styles.authBrand}>
          <View style={[styles.authBrandLogo, compactAuth && styles.authBrandLogoCompact]}>
            <Image source={require("./assets/zorlii-logo.png")} style={styles.authBrandImage} resizeMode="contain" />
          </View>
        </View>
        <Text style={styles.authEyebrow}>A thoughtful little corner</Text>
        <Text accessibilityRole="header" style={[styles.authTitle, compactAuth && styles.authTitleCompact]}>Zorlii</Text>
        <Text style={styles.authIntroLead}>Make room for the conversations that matter.</Text>
        {!compactAuth ? <Text style={styles.authIntroDescription}>Discover people and conversations, send private messages, and play mini games.</Text> : null}
      </View>
      <View style={[styles.form, styles.authForm, compactAuth && styles.authFormCompact]}>
        <Text accessibilityRole="header" style={styles.authFormTitle}>{title}</Text>
        <Text style={styles.authFormCopy}>{description}</Text>
        {children}
      </View>
    </>;
    if (screen === "games") return <Games apiUrl={API_URL} token={token}
      theme={{ accent: safeAccent, accentText: themeText, surface: palette.surface, raised: palette.raised,
        border: palette.border, text: "#f5f2ff", muted: palette.muted }}
      openProfile={username => { void openPublicProfile(username); }} />;
    if (screen === "terms") return <View style={styles.form}>
      <Text style={styles.title}>A quick community update</Text>
      <Text style={styles.copy}>To continue using Zorlii, confirm that you are at least 18 and accept the Terms of Use and Privacy Policy.</Text>
      {button("Read Terms of Use", () => { void Linking.openURL(`${API_URL}/terms`).catch(fail); }, true)}
      {button("Read Privacy Policy", () => { void Linking.openURL(`${API_URL}/privacy`).catch(fail); }, true)}
      {button("I’m 18+ and accept", acceptTerms)}
      {button("Sign out", logout, true)}
    </View>;
    if (screen === "thread") return <View onLayout={event => { threadTopRef.current = event.nativeEvent.layout.y; }}>
      <View style={styles.row}>
        {button("‹ Back", leaveThread, true)}
        <Pressable accessibilityRole="button" accessibilityState={{ disabled: threadRefreshing }}
          disabled={threadRefreshing} onPress={() => { void refreshThread(); }}
          style={({ pressed }) => [styles.button, styles.secondary, { borderColor: safeAccent }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
          <Text style={[styles.buttonText, styles.secondaryText, { color: safeAccent }]}>{threadRefreshing ? "Refreshing…" : "Refresh thread"}</Text>
        </Pressable>
      </View>
      <Text style={styles.eyebrow}>Conversation thread</Text>
      <Text style={styles.title}>Thread</Text>
      {threadPost ? postCard(threadPost) : null}
      {threadLoading && !threadReplies.length ? <ActivityIndicator color={safeAccent} accessibilityLabel="Loading thread" /> : null}
      {threadError ? <Text style={styles.copy} accessibilityLiveRegion="polite">{threadError}</Text> : null}
      {threadError && !threadReplies.length ? button("Retry loading thread", () => { void refreshThread(); }, true) : null}
      <Text style={styles.section}>Replies · {threadPost?.reply_count ?? threadReplies.length}</Text>
      <Text style={styles.copy} accessibilityLiveRegion="polite">{threadReplies.length
        ? `${threadReplies.length} replies loaded${threadHasMore ? " · more replies available" : ""}`
        : threadLoading ? "Loading replies…" : threadHasMore ? "More replies are available." : "No replies yet. Start the conversation."}</Text>
      {threadReplies.map(reply => <View key={reply.id} nativeID={`reply-${reply.id}`} onLayout={event => {
        if (threadTargetReplyRef.current !== reply.id) return;
        const requestId = threadRequestRef.current;
        const y = screenBodyTopRef.current + threadTopRef.current + event.nativeEvent.layout.y;
        requestAnimationFrame(() => {
          if (requestId !== threadRequestRef.current || threadTargetReplyRef.current !== reply.id) return;
          feedScrollRef.current?.scrollTo({ y: Math.max(0, y - 16), animated: !reduceMotion });
          threadTargetReplyRef.current = null;
        });
      }}>{replyCard(reply, threadPost?.id || 0)}</View>)}
      {threadHasMore ? <Pressable accessibilityRole="button" accessibilityState={{ disabled: threadLoadingMore }}
        disabled={threadLoadingMore} onPress={() => { void loadMoreThreadReplies(); }}
        style={({ pressed }) => [styles.button, styles.secondary, { borderColor: safeAccent }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
        <Text style={[styles.buttonText, styles.secondaryText, { color: safeAccent }]}>{threadLoadingMore ? "Loading replies…" : threadError ? "Retry loading replies" : "Load more replies"}</Text>
      </Pressable> : null}
      {threadPost ? threadComposer(threadPost) : null}
    </View>;
    if (screen === "report" && reportTarget) return <View style={styles.form}>
      <Text style={styles.title}>Report {reportTarget.label}</Text>
      <Text style={styles.copy}>Choose the reason that best describes the content or account. Reports are sent to the Zorlii moderation team.</Text>
      {[
        ["harassment", "Harassment or bullying"],
        ["hate", "Hateful content"],
        ["sexual", "Sexual content"],
        ["spam", "Spam or misleading content"],
        ["self_harm", "Self-harm or dangerous behavior"],
        ["other", "Something else"],
      ].map(([value, label]) => <Pressable key={value} accessibilityRole="radio" accessibilityState={{ selected: form.report_reason === value }} style={[styles.checkLine, themedSurface]} onPress={() => update("report_reason", value)}>
        <Text style={styles.copy}>{form.report_reason === value ? "◉" : "○"}  {label}</Text>
      </Pressable>)}
      {field("report_details", "Additional details (optional)", false, true)}
      {button("Send report", submitReport)}
      {button("Cancel", () => { setReportTarget(null); setScreen(reportReturnScreen.current); }, true)}
    </View>;
    if (screen === "register") return authJourney("Create your account", "Join people making room for the conversations that matter.", <>
      {field("email", "Email address", false, false, "Email")}
      {field("password", "Password", true, false, "Password")}
      <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: form.accept_terms === "true" }} style={[styles.checkLine, themedSurface]} onPress={() => update("accept_terms", String(form.accept_terms !== "true"))}>
        <Text style={styles.copy}>{form.accept_terms === "true" ? "☑" : "□"}  I am 18 or older and accept the Terms of Use and Privacy Policy.</Text>
      </Pressable>
      <View style={styles.authActionRow}>
        {authAction("Terms of Use", () => { void Linking.openURL(`${API_URL}/terms`).catch(fail); })}
        {authAction("Privacy Policy", () => { void Linking.openURL(`${API_URL}/privacy`).catch(fail); })}
      </View>
      {authAction("Continue to email verification", () => { void submitAuth(true); }, true, "Creating account…")}
      <View style={styles.authActionRow}>
        {authAction("Already joined? Sign in", () => setScreen("login"))}
      </View>
    </>);
    if (screen === "verify-register") return authJourney("Verify your email", `If your registration can be verified, a six-digit code may be sent to ${signupEmail}. It expires in 10 minutes.`, <>
      {field("code", "Six-digit code", false, false, "Six-digit code")}
      {authAction("Verify and create account", () => { void verifyRegistration(); }, true, "Verifying…")}
      <View style={styles.authActionRow}>
        {authAction("Resend code", () => { void runAuthAction(async () => {
          const result = await request("/api/auth/register/resend", "POST", { email: signupEmail });
          setError(result.message);
        }); })}
        {authAction("Start again", () => setScreen("register"))}
      </View>
    </>);
    if (screen === "login") return authJourney("Sign in", "Pick up where you left off.", <>
      {field("email", "Email address", false, false, "Email")}
      {field("password", "Password", true, false, "Password")}
      {authAction("Sign in", () => { void submitAuth(); }, true, "Signing in…")}
      <View style={styles.authActionRow}>
        {authAction("Create an account", () => setScreen("register"))}
        {authAction("Forgot password?", () => setScreen("forgot"))}
      </View>
    </>);
    if (screen === "forgot") return authJourney("Reset your password", "Enter your email. If an account exists, we’ll send a one-time code.", <>
      {field("email", "Email address", false, false, "Email")}
      {authAction("Send verification code", () => { void runAuthAction(async () => {
          const email = (form.email || "").trim().toLowerCase();
          const result = await request("/api/auth/forgot-password", "POST", { email });
          setRecoveryEmail(email);
          setForm(current => ({ ...current, email, code: "", password: "" }));
          setScreen("reset-code");
          setError(result.message);
        }); }, true, "Sending code…")}
      <View style={styles.authActionRow}>
        {authAction("Back to sign in", () => setScreen("login"))}
      </View>
    </>);
    if (screen === "reset-code") return authJourney("Choose a new password", `If ${recoveryEmail} belongs to an account, enter the emailed six-digit code. Codes expire in 10 minutes.`, <>
      {field("code", "Six-digit code", false, false, "Six-digit code")}
      {field("password", "New password", true, false, "New password")}
      {authAction("Verify code and update password", () => {
        const issue = passwordPolicyError(form.password || "");
        if (issue) { setError(issue); return; }
        void runAuthAction(async () => {
          await request("/api/auth/reset-password", "POST", {
            email: recoveryEmail, code: form.code, password: form.password,
          });
          await SecureStore.deleteItemAsync("zorlii_session");
          resetConversationState();
          setToken(""); updateMe(null); setScreen("login");
          setError("Password updated. Sign in with your new password.");
        });
      }, true, "Updating password…")}
      <View style={styles.authActionRow}>
        {authAction("Resend code", () => { void runAuthAction(async () => {
          const result = await request("/api/auth/forgot-password", "POST", { email: recoveryEmail });
          setError(result.message);
        }); })}
        {authAction("Change email", () => setScreen("forgot"))}
      </View>
    </>);
    if (screen === "delete-account") return <View style={styles.form}>
      <Text style={styles.title}>Delete account</Text>
      <Text style={styles.copy}>This permanently deletes your account, profile, posts, replies, follows, saved items, and messages you sent. Messages sent by other people remain in their accounts.</Text>
      {field("delete_password", "Current password", true)}
      {field("delete_confirmation", `Type ${me?.username || "your username"} to confirm`)}
      {button("Permanently delete my account", confirmAccountDeletion)}
      {button("Cancel", () => { setForm({}); setScreen("profile"); }, true)}
    </View>;
    if (screen === "notifications") return <View>
      <Text style={styles.title}>Activities</Text>
      <Text style={styles.copy}>Updates from members who follow, reply, react, repost, quote, mention, or message you.</Text>
      <View style={styles.row}>
        {button("Refresh", loadNotifications, true)}
        {unreadNotifications ? button("Mark all as read", markAllNotificationsRead, true) : null}
      </View>
      {loading ? <ActivityIndicator color={safeAccent} style={{ margin: 20 }} /> : null}
      {notifications.map(item => <View key={item.id} style={[styles.post, !item.read && styles.unreadNotification]}>
        <View style={styles.postAuthor}><Avatar user={item.actor} size={38} onPress={profilePhotoAction(item.actor)} /><View>
          {profileLink(item.actor.username, item.actor.display_name)}
          {profileLink(item.actor.username, `@${item.actor.username}`, styles.handle)}
        </View></View>
        <Text style={styles.copy}>{item.kind === "mention"
          ? <>{profileLink(item.actor.username, `@${item.actor.username}`)} mentioned you.</>
          : activityDescription(item.kind)}</Text>
        {item.kind === "mention" && item.post_id
          ? button("View mentioned post", () => { void openMentionTarget(item); }, true)
          : null}
        <Text style={styles.handle}>{item.created_at}</Text>
        {!item.read ? button("Mark as read", () => markNotificationRead(item.id), true) : <Text style={styles.handle}>Read</Text>}
      </View>)}
      {!loading && !notifications.length ? <View style={[styles.empty, themedSurface]}><BrandHalo size={54} quiet /><Text style={styles.section}>You’re all caught up.</Text><Text style={styles.copy}>New activity from members will appear here.</Text></View> : null}
    </View>;
    if (screen === "social-profile") return <View>
      {button("‹ Back", () => setScreen(profileReturnScreenRef.current), true)}
      {publicProfile ? <>
        <View style={styles.profileHero}>
          <Avatar user={publicProfile} size={78} onPress={profilePhotoAction(publicProfile)} />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={styles.title}>{publicProfile.display_name}</Text>
            {profileLink(publicProfile.username, `@${publicProfile.username}`, styles.handle)}
            <View style={styles.row}>
              <Pressable accessibilityRole="button" accessibilityLabel={`${publicProfile.follower_count} followers`} style={[styles.countCard, themedRaised]} onPress={() => { void openSocialList(publicProfile.username, "followers"); }}><Text style={styles.countValue}>{publicProfile.follower_count}</Text><Text style={styles.countLabel}>Followers</Text></Pressable>
              <Pressable accessibilityRole="button" accessibilityLabel={`${publicProfile.following_count} following`} style={[styles.countCard, themedRaised]} onPress={() => { void openSocialList(publicProfile.username, "following"); }}><Text style={styles.countValue}>{publicProfile.following_count}</Text><Text style={styles.countLabel}>Following</Text></Pressable>
            </View>
            {formatJoinedDate(publicProfile.joined_at || publicProfile.created_at, me?.language) ? <Text style={[styles.handle, { marginTop: 4 }]}>{formatJoinedDate(publicProfile.joined_at || publicProfile.created_at, me?.language)}</Text> : null}
          </View>
        </View>
        <Text style={styles.section}>A little about you</Text>
        <Text style={styles.copy}>{publicProfile.bio || "A Zorlii member."}</Text>
        <View style={styles.row}>
          <View style={[styles.countCard, themedRaised]}><Text style={styles.countValue}>{publicProfilePosts.length}</Text><Text style={styles.countLabel}>Loaded posts</Text></View>
        </View>
        <View style={styles.row}>
          {publicProfile.id !== me?.id ? followButton(publicProfile) : null}
          {button("Message", () => startConversation(publicProfile.username), true)}
          {button("Safety", () => showSafetyOptions(publicProfile), true)}
        </View>
        <Text style={styles.section}>Posts</Text>
        {publicProfilePosts.map(post => postCard(post))}
        {!publicProfilePosts.length ? <Text style={styles.copy}>No posts to show yet.</Text> : null}
        {publicProfileHasMore ? <Pressable accessibilityRole="button"
          accessibilityState={{ disabled: loadingPublicProfileOlder }}
          disabled={loadingPublicProfileOlder} onPress={() => { void loadOlderProfilePosts(true); }}
          style={({ pressed }) => [styles.button, styles.secondary, { borderColor: safeAccent }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
          <Text style={[styles.buttonText, styles.secondaryText, { color: safeAccent }]}>{loadingPublicProfileOlder ? "Loading older posts…" : "Load older posts"}</Text>
        </Pressable> : null}
      </> : !loading ? <Text style={styles.copy}>This profile could not be loaded.</Text> : null}
    </View>;
    if (screen === "social-followers" || screen === "social-following") {
      const isFollowers = screen === "social-followers";
      const people = socialList?.users || [];
      const owner = socialList?.username || me?.username || "";
      return <View>
        {button("‹ Profile", () => { if (owner.toLowerCase() === me?.username.toLowerCase()) void loadProfile(); else void openPublicProfile(owner); }, true)}
        <Text style={styles.title}>{isFollowers ? "Followers" : "Following"}</Text>
        <Text style={styles.copy}>@{owner} · {socialList?.count ?? 0} {isFollowers ? "followers" : "following"}</Text>
        {people.map(person => <View key={person.id} style={styles.memberRow}>
          <Avatar user={person} size={40} onPress={profilePhotoAction(person)} />
          <View style={styles.memberIdentity}>{profileLink(person.username, person.display_name)}{profileLink(person.username, `@${person.username}`, styles.handle)}</View>
          {followButton(person)}
          {button("Message", () => startConversation(person.username), true)}
        </View>)}
        {socialListLoading ? <ActivityIndicator color={safeAccent} /> : null}
        {!socialListLoading && !people.length && !error ? <View style={[styles.empty, themedSurface]}><Text style={styles.section}>{isFollowers ? "No followers yet" : "Not following anyone yet"}</Text><Text style={styles.copy}>Member lists will appear here as your community grows.</Text></View> : null}
        {!socialListLoading && socialList && people.length < socialList.count && people.length > 0
          ? button("Load more members", () => openSocialList(owner, socialList.kind, people.length), true) : null}
      </View>;
    }
    if (screen === "hashtag") return <View>
      <Text style={[styles.eyebrow, { color: safeAccent }]}>Explore conversations</Text><Text style={styles.title}>#{hashtag}</Text>
      <Text style={styles.copy}>Posts with this hashtag.</Text>
      {hashtagPosts.map(post => postCard(post))}
      {hashtagLoading ? <ActivityIndicator color={safeAccent} /> : null}
      {!hashtagLoading && !hashtagPosts.length && !error ? <Text style={styles.copy}>No posts with this hashtag yet.</Text> : null}
      {!hashtagLoading && hashtagHasMore && hashtagPosts.length
        ? button("Load older posts", () => openHashtag(hashtag, hashtagPosts[hashtagPosts.length - 1].id), true) : null}
    </View>;
    if (screen === "blocked") return <View>
      {button("‹ Profile", loadProfile, true)}
      <Text style={styles.title}>Blocked accounts</Text>
      <Text style={styles.copy}>Members you’ve blocked cannot interact with you through posts, follows, or messages.</Text>
      {blockedUsers.map(person => <View key={person.id} style={styles.memberRow}>
        <Avatar user={person} size={40} onPress={profilePhotoAction(person)} />
        <View style={styles.memberIdentity}>{profileLink(person.username, person.display_name)}{profileLink(person.username, `@${person.username}`, styles.handle)}</View>
        {button("Unblock", () => unblockUser(person.username), true)}
      </View>)}
      {!blockedUsers.length ? <View style={[styles.empty, themedSurface]}><Text style={styles.section}>No blocked accounts</Text><Text style={styles.copy}>Your blocked-account list is empty.</Text></View> : null}
    </View>;
    if (screen === "explore") return <View>
      <Text style={styles.title}>Explore</Text><Text style={styles.copy}>Search real member profiles and public posts.</Text>
      {field("query", "Search names, handles, and posts")}
      {button("Search", async () => {
        if (!blockedUsersLoaded) { setError("Blocked accounts are still loading. Try again shortly."); return; }
        const requestId = ++searchRequestRef.current;
        try {
          const result = await request(`/api/search?q=${encodeURIComponent((form.query || "").trim())}`);
          if (requestId !== searchRequestRef.current) return;
          const blocked = new Set(blockedUsers.map(person => person.username.toLowerCase()));
          const people = (result.people || []).filter((person: Member) => !blocked.has(person.username.toLowerCase()));
          setSearch({ ...result, people });
          void hydrateFollowStates(people);
        } catch (e) { fail(e); }
      })}
      {search ? <View accessibilityLiveRegion="polite">
        <Text style={styles.section}>People</Text>{search.people.map((person: any) => <View key={person.id} style={styles.post}>
          <View style={styles.postAuthor}><Avatar user={person} onPress={profilePhotoAction(person)} /><View>
            {profileLink(person.username, person.display_name)}
            {profileLink(person.username, `@${person.username}`, styles.handle)}
          </View></View>
          <Text style={styles.copy}>{person.bio || "A Zorlii member"}</Text>{followButton(person)}
          {button("Message", () => startConversation(person.username), true)}
          {button("Safety", () => showSafetyOptions(person), true)}
        </View>)}
        <Text style={styles.section}>Public posts</Text>{search.posts.map((post: Post) => postCard(post))}
        {!search.people.length && !search.posts.length ? <Text style={styles.copy}>No matching people or public posts yet.</Text> : null}
      </View> : <Text style={styles.copy}>No search results yet.</Text>}
    </View>;
    if (screen === "inbox") return <View>
      <Text style={styles.title}>Inbox</Text><Text style={styles.copy}>Private messages are visible only to conversation participants.</Text>
      <View style={[styles.startConversation, themedSurface]}>
        <Text style={styles.section}>Start a conversation</Text>
        {field("recipient", "Search by username")}
        {button("Find members", searchInboxMembers)}
        {inboxSearchResults.map(person => <View key={person.id} style={styles.memberRow}>
          <Avatar user={person} size={40} onPress={profilePhotoAction(person)} />
          <View style={styles.memberIdentity}>{profileLink(person.username, person.display_name)}{profileLink(person.username, `@${person.username}`, styles.handle)}</View>
          {button("Message", () => startConversation(person.username), true)}
        </View>)}
        {inboxSearchResults.length === 0 && form.recipient ? <Text style={styles.handle}>Search for a member to begin.</Text> : null}
      </View>
      <Text style={styles.section}>Your conversations</Text>
      {conversations.map(c => {
        const person = c.participants.find(participant => participant.id !== me?.id) || c.participants[0];
        return <View key={c.id} style={[styles.threadRow, themedSurface]}>
          <Avatar user={person} size={42} onPress={profilePhotoAction(person)} />
          <View style={styles.memberIdentity}>
            {person ? profileLink(person.username, person.display_name) : <Text style={styles.author}>Conversation</Text>}
            {person ? profileLink(person.username, `@${person.username}`, styles.handle) : null}
            <Text numberOfLines={1} style={styles.copy}>{c.last_message || "No messages yet"}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel={`Open conversation with @${person?.username || "member"}`}
              onPress={() => loadConversation(c.id)} style={styles.threadOpen}>
              <Text style={styles.threadOpenText}>Open conversation →</Text>
            </Pressable>
          </View>
        </View>;
      })}
      {!conversations.length && <View style={[styles.welcomeNote, themedSurface]}>
        <Text style={styles.section}>🎉 Welcome to Zorlii!</Text>
        <Text style={styles.copy}>Your space to connect, share, discover and have fun!</Text>
        <Text style={styles.copy}>Join conversations, share your thoughts, meet new people, express yourself, repost what inspires you, and enjoy exciting mini-games along the way.</Text>
        <Text style={styles.copy}>Whether you're here to make friends, explore ideas or simply have a good time, there's a place for you on Zorlii.</Text>
        <Text style={styles.copy}>Connect freely. Share boldly. Be yourself.</Text>
        <Text style={styles.copy}>💜 Welcome to the Zorlii community. Let's make every connection count! — Creator</Text>
      </View>}
    </View>;
    if (screen === "messages") {
      const person = conversations.find(item => item.id === conversationId)?.participants.find(item => item.id !== me?.id);
      return <View style={styles.conversationScreen}>
        <View style={[styles.conversationHeader, { borderBottomColor: palette.border }]}>
          <Pressable accessibilityRole="button" accessibilityLabel="Back to inbox" onPress={leaveConversation} style={styles.conversationBack}>
            <Text style={[styles.conversationBackText, { color: safeAccent }]}>‹</Text>
          </Pressable>
          <View style={styles.conversationIdentity}>
            {person ? profileLink(person.username, person.display_name, styles.conversationTitle) : <Text style={styles.conversationTitle}>Conversation</Text>}
            {person ? <Text style={styles.handle}>@{person.username}</Text> : null}
          </View>
          {person ? <Pressable accessibilityRole="button" accessibilityLabel="Conversation safety options" onPress={() => showSafetyOptions(person)} style={styles.conversationSafety}>
            <Text style={[styles.conversationSafetyText, { color: safeAccent }]}>···</Text>
          </Pressable> : null}
        </View>
        {error ? <Pressable accessibilityRole="button" accessibilityLabel={`Dismiss error: ${error}`} onPress={() => setError("")} style={styles.error}><Text style={styles.errorText}>{error}  ×</Text></Pressable> : null}
        <View style={styles.messageList}>
          <Text style={styles.conversationDate}>{conversationCreatedAt
            ? `Conversation started ${formatConversationDate(conversationCreatedAt)}`
            : "Conversation date unavailable"}</Text>
          <ScrollView ref={messageScrollRef} style={styles.messageScroll} contentContainerStyle={styles.messageScrollContent}
            nestedScrollEnabled keyboardShouldPersistTaps="handled"
            onScroll={event => { messageScrollYRef.current = event.nativeEvent.contentOffset.y; }}
            onScrollBeginDrag={() => { messageLatestTargetRef.current = null; }}
            scrollEventThrottle={16}>
            {hasMoreMessages ? <Pressable accessibilityRole="button" accessibilityLabel="Load older messages"
              accessibilityState={{ disabled: loadingOlderMessages }} disabled={loadingOlderMessages}
              onPress={() => { void loadOlderMessages(); }} style={styles.loadOlderButton}>
              {loadingOlderMessages ? <ActivityIndicator color="#cdb6ff" /> : <Text style={styles.loadOlderText}>↑  Load older messages</Text>}
            </Pressable> : null}
            {loadingMessages && !messages.length
              ? <ActivityIndicator color={safeAccent} style={{ margin: 20 }} />
              : !messages.length ? <Text style={styles.copy}>No messages yet. Send a note to begin.</Text> : messages.map(message =>
              <View key={message.id} onLayout={event => onMessageLayout(message.id, event.nativeEvent.layout.y)}
              style={[styles.message, { backgroundColor: message.sender_id === me?.id ? palette.raised : palette.surface, borderColor: palette.border }, message.sender_id === me?.id && styles.myMessage]}>
                {message.sender_id === me?.id
                  ? <Text style={styles.messageAuthor}>You</Text>
                  : profileLink(message.author.username, `@${message.author.username}`, styles.messageAuthor)}
                <Text style={styles.messageBody}>{taggedText(message.body)}</Text>
                <Text style={styles.messageTime}>{formatMessageTime(message.created_at)}</Text>
              </View>)}
          </ScrollView>
        </View>
        <View style={[styles.messageComposer, { borderColor: palette.border, backgroundColor: palette.input }]}>
          <TextInput accessibilityLabel="Write a message" placeholder="Write a message…" placeholderTextColor={palette.muted}
            multiline maxLength={4000} value={form.message || ""} onChangeText={value => {
              if (conversationId !== null) {
                messageDraftsRef.current[conversationId] = value;
                messageDraftVersionRef.current[conversationId] = (messageDraftVersionRef.current[conversationId] || 0) + 1;
              }
              update("message", value);
            }}
            style={[styles.messageComposerInput, { color: "#f5f2ff" }]} />
          <Pressable accessibilityRole="button" accessibilityLabel="Send message" accessibilityState={{ disabled: sendingMessage }}
            disabled={sendingMessage} onPress={async () => {
              if (!form.message?.trim() || conversationId === null || sendingMessageRef.current) return;
              const id = conversationId;
              const generation = conversationGenerationRef.current;
              const draftVersion = messageDraftVersionRef.current[id] || 0;
              const body = form.message;
              sendingMessageRef.current = true;
              setSendingMessage(true);
              try {
                await request(`/api/conversations/${id}/messages`, "POST", { body });
                if ((messageDraftVersionRef.current[id] || 0) === draftVersion) messageDraftsRef.current[id] = "";
                if (conversationGenerationRef.current !== generation) return;
                if (activeConversationIdRef.current !== id) return;
                setForm(current => ({ ...current, message: current.message === body ? "" : current.message }));
                await refreshConversationMessages(id, true);
              } catch (e) { if (activeConversationIdRef.current === id && conversationGenerationRef.current === generation) fail(e); }
              finally { sendingMessageRef.current = false; setSendingMessage(false); }
            }} style={({ pressed }) => [styles.arrowSubmit, { backgroundColor: safeAccent }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
            <Text style={[styles.arrowSubmitText, { color: themeText }]} accessibilityElementsHidden>➤</Text>
          </Pressable>
        </View>
      </View>;
    }
    if (screen === "profile") return <View>
      <View style={styles.profileHero}>
        <View style={styles.profileAvatarWrap}>
          <Avatar user={me} size={88} onPress={profilePhotoAction(me)} />
          <Pressable accessibilityRole="button" accessibilityLabel="Upload profile photo"
            accessibilityHint="Choose a new photo for your profile."
            onPress={pickAvatar} style={({ pressed }) => [styles.avatarUploadButton, { backgroundColor: safeAccent }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
            <Text style={[styles.avatarUploadText, { color: themeText }]} accessibilityElementsHidden>+</Text>
          </Pressable>
        </View>
        <View style={{ flex: 1, minWidth: 0 }}>
          {me?.username ? profileLink(me.username, me.display_name || "Your profile", styles.title) : <Text style={styles.title}>Your profile</Text>}
          {me?.username ? profileLink(me.username, `@${me.username}`, styles.handle) : null}
          <View style={styles.row}>
            <Pressable accessibilityRole="button" accessibilityLabel={`${followerCount} followers`} style={[styles.countCard, themedRaised]} onPress={() => { if (me) void openSocialList(me.username, "followers"); }}><Text style={styles.countValue}>{followerCount}</Text><Text style={styles.countLabel}>Followers</Text></Pressable>
            <Pressable accessibilityRole="button" accessibilityLabel={`${followingCount} following`} style={[styles.countCard, themedRaised]} onPress={() => { if (me) void openSocialList(me.username, "following"); }}><Text style={styles.countValue}>{followingCount}</Text><Text style={styles.countLabel}>Following</Text></Pressable>
          </View>
          {formatJoinedDate(me?.joined_at || me?.created_at, me?.language) ? <Text style={[styles.handle, { marginTop: 4 }]}>{formatJoinedDate(me?.joined_at || me?.created_at, me?.language)}</Text> : null}
        </View>
      </View>
      <Text style={styles.section}>A little about you</Text>
      <Text style={styles.copy}>{me?.bio || "Add a little about you to help others get to know you."}</Text>
      <View style={styles.row}>
        <View style={[styles.countCard, themedRaised]}><Text style={styles.countValue}>{activityCounts?.posts ?? "—"}</Text><Text style={styles.countLabel}>Posts</Text></View>
      </View>
      <View style={styles.activityGrid}>
        {(["media", "replies", "likes", "echoes", "saved", "messages"] as const).map(key => <View key={key} style={[styles.countCard, styles.activityMetric]}>
          <Text style={styles.countValue}>{activityCounts?.[key] ?? "—"}</Text>
          <Text style={styles.countLabel}>{key === "messages" ? "Messages sent" : key[0].toUpperCase() + key.slice(1)}</Text>
        </View>)}
      </View>
      <Text style={styles.section}>Your posts</Text>
      {profilePosts.map(post => postCard(post))}
      {!profilePosts.length ? <Text style={styles.copy}>Your posts will appear here when you share them.</Text> : null}
      {profileHasMore ? <Pressable accessibilityRole="button" accessibilityState={{ disabled: loadingProfileOlder }}
        disabled={loadingProfileOlder} onPress={() => { void loadOlderProfilePosts(false); }}
        style={({ pressed }) => [styles.button, styles.secondary, { borderColor: safeAccent }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
        <Text style={[styles.buttonText, styles.secondaryText, { color: safeAccent }]}>{loadingProfileOlder ? "Loading older posts…" : "Load older posts"}</Text>
      </Pressable> : null}
    </View>;
    if (screen === "settings") return <View>
      <Text style={[styles.eyebrow, { color: safeAccent }]}>Your account</Text>
      <Text style={styles.title}>Settings</Text>
      <Text style={styles.copy}>Your appearance, profile, privacy and account controls.</Text>
      <View style={[styles.settingsPanel, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <Text style={styles.section}>Appearance</Text>
        <Text style={styles.copy}>Choose a colour from the full spectrum. Your accent, surfaces, borders and controls update together with readable text.</Text>
        <View style={styles.row}>
            <View style={[styles.colorSwatch, { backgroundColor: themeColor, borderColor: palette.border }]}
                accessible accessibilityRole="image" accessibilityLabel={`Selected accent colour preview ${themeColor}`} />
        </View>
          <HueSpectrumPicker value={themeColorDraft} onChange={setThemeColorDraft} />
        {button("Save appearance", saveThemeColor)}
      </View>
      <Text style={styles.section}>Profile and privacy</Text>
      {disclosure("edit-profile", "Edit profile", <>
        {field("username", "Username (3–24 letters, numbers, or underscores)")}
        {field("display_name", "Display name")}
        {field("bio", "A little about you", false, true)}
        {field("interests", "Interests, separated by commas")}
        {me?.avatar_url ? button("Remove profile photo", confirmAvatarRemoval, true) : null}
        {button("Save profile", () => { void saveProfileSection("profile"); })}
      </>)}
      {disclosure("privacy-tools", "Privacy & local tools", <>
        {button(`Blocked accounts · ${blockedUsers.length}`, () => setScreen("blocked"), true)}
        <Text style={styles.copy}>Features stay off until you opt in. Recommendations compare real public posts; context help selects supplied sentences. No generative AI is used.</Text>
        <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: form.recommendations_consent ? form.recommendations_consent === "true" : Boolean(me?.recommendations_consent) }} style={styles.checkLine} onPress={() => update("recommendations_consent", String(!(form.recommendations_consent ? form.recommendations_consent === "true" : me?.recommendations_consent)))}><Text>{(form.recommendations_consent ? form.recommendations_consent === "true" : me?.recommendations_consent) ? "☑" : "□"}  Local recommendations from real public posts. No generative AI service.</Text></Pressable>
        <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: form.context_assistance_consent ? form.context_assistance_consent === "true" : Boolean(me?.context_assistance_consent) }} style={styles.checkLine} onPress={() => update("context_assistance_consent", String(!(form.context_assistance_consent ? form.context_assistance_consent === "true" : me?.context_assistance_consent)))}><Text>{(form.context_assistance_consent ? form.context_assistance_consent === "true" : me?.context_assistance_consent) ? "☑" : "□"}  Local extractive context help. Each request needs confirmation; no answer is generated.</Text></Pressable>
        {button("Save privacy choices", () => { void saveProfileSection("privacy"); })}
        {me?.recommendations_consent ? <>
          <Text style={styles.section}>Member suggestions</Text>
          <Text style={styles.copy}>A local comparison of opted-in interests and real public posts, not a generative AI service.</Text>
          {button("Find members from real posts", async () => {
            try {
              const people = (await request("/api/recommendations")).recommendations;
              setRecommendations(people);
              void hydrateFollowStates(people);
            }
            catch (e) { fail(e); }
          }, true)}
          {recommendations.map(person => <View key={person.id} style={styles.post}>
            <View style={styles.postAuthor}><Avatar user={person} onPress={profilePhotoAction(person)} /><View>
              {profileLink(person.username, person.display_name)}
              {profileLink(person.username, `@${person.username}`, styles.handle)}
            </View></View>
            <Text style={styles.copy}>{person.bio || "A member sharing public posts."}</Text>
            {followButton(person)}
            {button("Message", () => startConversation(person.username), true)}
          </View>)}
          {!recommendations.length ? <Text style={styles.copy}>Suggestions use real public member posts; none may be available yet.</Text> : null}
        </> : null}
      </>)}
      {disclosure("local-context", "Local context help", <>
        <Text style={styles.copy}>Your text is processed in memory only. Opt in under Privacy &amp; local tools, then confirm each request.</Text>
        {field("context_text", "Paste text you want help with", false, true)}
        {field("context_question", "What would you like to find?", false)}
        <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: form.context_confirm === "true" }} style={styles.checkLine} onPress={() => update("context_confirm", form.context_confirm === "true" ? "false" : "true")}>
          <Text>{form.context_confirm === "true" ? "☑" : "□"}  Use this text locally for this request</Text>
        </Pressable>
        {button("Find relevant sentences", async () => {
          if (form.context_confirm !== "true") { setError("Confirm use of this text for this request first."); return; }
          try {
            const result = await request("/api/context", "POST", {
              text: form.context_text || "", question: form.context_question || "", consent_for_this_request: true,
            });
            setContextResult(result.sentences.length ? result.sentences.join("\n\n") : "No relevant sentences found.");
            update("context_confirm", "false");
          } catch (e) { fail(e); }
        })}
        {contextResult ? <Text style={styles.copy}>{contextResult}</Text> : null}
      </>)}
      {disclosure("account-help", "Notifications, help & account", <>
        <Text style={styles.copy}>Get activity alerts when Zorlii is in the background.</Text>
        {button("Enable activity alerts", async () => {
          const retryToken = token;
          const generation = pushSessionGenerationRef.current;
          try {
            const enabled = await registerPushToken(retryToken, true);
            if (pushSessionRef.current !== retryToken || pushSessionGenerationRef.current !== generation) return;
            if (enabled === "blocked") {
              Alert.alert("Notifications are blocked", "Notifications are disabled for Zorlii. Open your device settings to allow them, then return and try again.", [
                { text: "Not now", style: "cancel" },
                { text: "Open settings", onPress: () => { void Linking.openSettings().catch(fail); } },
              ]);
            } else {
              Alert.alert(enabled ? "Activity alerts enabled" : "Notifications are off",
                enabled ? "This device is registered for Zorlii activity alerts." : "Allow notifications when prompted, then try again.");
            }
          } catch (e) {
            if (pushSessionRef.current !== retryToken || pushSessionGenerationRef.current !== generation) return;
            if (isTransientPushServiceUnavailable(e)) Alert.alert("Temporary notification service issue", pushRegistrationErrorMessage(e));
            else fail(e);
          }
        }, true)}
        <Text style={styles.section}>Your data</Text>
        <Text style={styles.copy}>Export a copy of your account data or permanently close your account.</Text>
        {button("Export my account data", exportAccount, true)}
        {button("Privacy Policy", () => { void Linking.openURL(`${API_URL}/privacy`).catch(fail); }, true)}
        {button("Terms of Use", () => { void Linking.openURL(`${API_URL}/terms`).catch(fail); }, true)}
        {button("Request account deletion online", () => { void Linking.openURL(`${API_URL}/account-deletion`).catch(fail); }, true)}
        {button("Delete account", () => { setForm({}); setScreen("delete-account"); })}
        {button("Sign out", logout, true)}
      </>)}
      {me?.is_moderator ? disclosure("moderator-reports", "Moderator reports", <>
        {button("Refresh open reports", loadModerationReports, true)}
        {moderationReports.map(report => <View key={report.id} style={styles.post}>
          <Text style={styles.author}>{report.target_type === "post" ? "Post" : "Account"} · {report.target_username ? `@${report.target_username}` : "removed content"}</Text>
          {report.post_body ? <Text style={styles.copy}>{taggedText(report.post_body)}</Text> : null}
          <Text style={styles.handle}>Reported by @{report.reporter_username} · {report.reason} · {report.created_at}</Text>
          {report.details ? <Text style={styles.copy}>{report.details}</Text> : null}
          <View style={styles.row}>
            {report.post_id ? button("Remove post", () => removeReportedPost(report), true) : null}
            {button("Mark reviewed", () => updateModerationReport(report.id, "reviewed"), true)}
            {button("Dismiss", () => updateModerationReport(report.id, "dismissed"), true)}
          </View>
        </View>)}
        {!moderationReports.length ? <Text style={styles.copy}>No open reports are currently loaded.</Text> : null}
      </>) : null}
    </View>;
    return <View>
      <Text style={[styles.eyebrow, { color: safeAccent }]}>Your community, in focus</Text>
      <View style={styles.pulseHeading}>
        <Text style={styles.title}>Pulse</Text>
        <Pressable accessibilityRole="button" accessibilityLabel="Refresh Pulse" accessibilityHint="Load the latest posts."
          onPress={() => { void loadFeed(scope, true); }} style={({ pressed }) => [styles.refreshButton, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
          <Text style={[styles.refreshButtonText, { color: safeAccent }]} accessibilityElementsHidden>↻</Text>
        </Pressable>
      </View>
      <View style={styles.row}>{button("Everyone", () => loadFeed("all"), true)}{button("Following", () => loadFeed("following"), true)}{button("Saved", () => loadFeed("bookmarks"), true)}</View>
      <View style={[styles.composerRow, styles.postComposerRow, { borderColor: palette.border, backgroundColor: palette.input }]}>
        <TextInput ref={composerRef} accessibilityLabel="Write a post" placeholder="What would you like to share?" placeholderTextColor={palette.muted}
          multiline maxLength={5000} value={form.post || ""} onChangeText={value => updateComposerText("post", value)}
          onSelectionChange={event => updateComposerSelection("post", form.post || "", event.nativeEvent.selection)}
          selection={composerSelections.post} style={[styles.postComposerInput, { color: "#f5f2ff" }]} />
        <MediaPickerButton label="Attach photos, videos, or GIFs to post" onPress={() => pickPostMedia()} />
        <Pressable accessibilityRole="button" accessibilityLabel="Share post" accessibilityHint="Publish this post to Pulse."
          onPress={() => { void sharePost(); }} style={({ pressed }) => [styles.arrowSubmit, { backgroundColor: safeAccent }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
          <Text style={[styles.arrowSubmitText, { color: themeText }]} accessibilityElementsHidden>➤</Text>
        </Pressable>
      </View>
      {mentionPicker("post")}
      {quoteTarget ? <View style={[styles.quotePreview, { backgroundColor: palette.surface, borderColor: palette.border }]}>
        <Text style={[styles.quotedLabel, { color: safeAccent }]}>Echo with a thought · original {quoteTarget.type}</Text>
        <View style={styles.postAuthor}><Avatar user={quoteTarget.item.author} size={30} onPress={profilePhotoAction(quoteTarget.item.author)} /><View>
          {profileLink(quoteTarget.item.author.username, quoteTarget.item.author.display_name)}
          {profileLink(quoteTarget.item.author.username, `@${quoteTarget.item.author.username}`, styles.handle)}
        </View></View>
        <Text numberOfLines={3} style={styles.copy}>{taggedText(quoteTarget.item.body || "Media post")}</Text>
        {mediaContent(quoteTarget.item.media)}
        {button("Remove original", () => setQuoteTarget(null), true)}
      </View> : null}
      <View style={styles.row}><Text style={styles.copy}>Visible to: </Text><Pressable onPress={() => update("visibility", form.visibility === "public" ? "followers" : form.visibility === "followers" ? "private" : "public")}><Text style={[styles.link, { color: readableAccent(activeThemeAccent) }]}>{form.visibility || "public"} ⌄</Text></Pressable></View>
      {postMedia.length ? button("Clear media", () => setPostMedia([]), true) : null}
      {postMedia.length ? <ScrollView horizontal style={styles.mediaSelection} contentContainerStyle={styles.mediaSelectionContent}>
        {postMedia.map((asset, index) => <View key={`${asset.assetId || asset.uri}-${index}`} style={styles.mediaSelectionItem}>
          {asset.type === "video" ? <Text style={styles.mediaSelectionText}>Video</Text> : <Image source={{ uri: asset.uri }} style={styles.mediaSelectionImage} />}
          <Pressable accessibilityRole="button" accessibilityLabel={`Remove selected media ${index + 1}`} style={styles.mediaRemove} onPress={() => setPostMedia(current => current.filter((_, itemIndex) => itemIndex !== index))}><Text style={styles.mediaRemoveText}>×</Text></Pressable>
        </View>)}
      </ScrollView> : null}
      {feedLoading || loading ? <ActivityIndicator color={safeAccent} style={{ margin: 20 }} /> : null}
      {posts.length ? <View style={[styles.pulseTimeline, { borderLeftColor: palette.border }]}>{posts.map(post => postCard(post))}</View> : null}
      {!feedLoading && !loading && posts.length === 0 ? <View style={[styles.empty, themedSurface]}><BrandHalo size={58} quiet /><Text style={styles.section}>Nothing here just yet.</Text><Text style={styles.copy}>Conversations shared by real Zorlii members will appear here. Explore public profiles, share a thought, or start a private conversation.</Text>{button("Explore people and conversations", () => setScreen("explore"), true)}</View> : null}
    </View>;
  }

  const authScreenActive = ["login", "register", "forgot", "verify-register", "reset-code"].includes(screen);
  return <KeyboardAvoidingView style={[styles.screen, authScreenActive ? styles.authScreenBackground : { backgroundColor: palette.background }]} behavior={Platform.OS === "ios" ? "padding" : "height"} keyboardVerticalOffset={0}>
    <StatusBar style="light" />
    {screen !== "messages" && !authScreenActive ? <View style={[styles.header, { paddingTop: 10 + insets.top, borderBottomColor: palette.border, backgroundColor: palette.surface }]}>
      <BrandHalo size={42} showLogo /><View style={styles.headerCopy}><Text style={styles.brand}>Zorlii</Text><Text style={styles.headerSub} numberOfLines={1}>People · posts · messages · games</Text></View>
      {me?.terms_accepted ? <Pressable ref={menuToggleRef} accessibilityRole="button"
        accessibilityLabel={unreadNotifications ? `Open menu, ${unreadNotifications} unread activities` : "Open menu"}
        accessibilityHint="Open profile tools, settings and account navigation."
        accessibilityState={{ expanded: menuOpen }} onPress={() => setMenuOpen(true)}
        style={({ pressed }) => [styles.menuToggle, { borderColor: `${safeAccent}88` }, pressed && (reduceMotion ? styles.buttonPressedReduced : styles.buttonPressed)]}>
        <Text style={[styles.menuToggleText, { color: safeAccent }]} accessibilityElementsHidden>☰</Text>
        {unreadNotifications ? <View style={[styles.menuUnreadBadge, styles.menuToggleBadge, { backgroundColor: safeAccent }]} accessibilityElementsHidden><Text style={[styles.menuUnreadText, { color: themeText }]}>{unreadNotifications}</Text></View> : null}
      </Pressable> : null}
    </View> : null}
    {screen === "messages" ? <View style={[styles.conversationScreen, { paddingTop: insets.top, paddingBottom: Math.max(insets.bottom, 8) }]}>{renderBody()}</View> :
    <ScrollView ref={feedScrollRef} style={[styles.scroll, authScreenActive ? styles.authScroll : { backgroundColor: palette.background }]} keyboardShouldPersistTaps="handled" keyboardDismissMode={Platform.OS === "ios" ? "interactive" : "on-drag"}
      automaticallyAdjustKeyboardInsets={Platform.OS === "ios"} contentContainerStyle={authScreenActive
        ? [styles.content, styles.authContent, { paddingTop: compactAuth ? Math.max(12, insets.top) : Math.max(20, insets.top + 10), paddingBottom: Math.max(insets.bottom, 24) }]
        : styles.content}
      onScroll={event => { feedScrollYRef.current = event.nativeEvent.contentOffset.y; }} scrollEventThrottle={16}>
      {error ? <Pressable onPress={() => setError("")} style={styles.error}><Text style={styles.errorText}>{error}  ×</Text></Pressable> : null}
      {loading && screen !== "feed" ? <ActivityIndicator color={safeAccent} /> : null}
      <Animated.View onLayout={event => { screenBodyTopRef.current = event.nativeEvent.layout.y; }} style={[{ opacity: screenOpacity, transform: [{ translateY: screenOffset }] }, authScreenActive && styles.authBody]}>
        {renderBody()}
      </Animated.View>
    </ScrollView>}
    {me?.terms_accepted && screen !== "messages" && !authScreenActive ? <View style={{ paddingBottom: insets.bottom, backgroundColor: palette.surface }}>{nav()}</View> : null}
    <Modal visible={menuOpen} transparent animationType="none" onRequestClose={() => closeMenu()}>
      <View style={styles.menuModalRoot} accessibilityViewIsModal>
        <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.menuScrim, { opacity: menuScrimOpacity }]} />
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="Close menu"
          onPress={() => closeMenu()} />
        <Animated.View style={[styles.menuDrawer, { width: menuDrawerWidth, paddingTop: insets.top + 16, paddingBottom: insets.bottom + 18,
          backgroundColor: palette.surface, borderColor: palette.border, transform: [{ translateX: menuTranslateX }] }]}>
          <View style={styles.menuHeading}><Text style={styles.menuTitle}>Your Zorlii</Text>
            <Pressable ref={menuCloseButtonRef} accessibilityRole="button" accessibilityLabel="Close menu" onPress={() => closeMenu()} style={styles.menuClose}>
              <Text style={styles.menuCloseText}>×</Text>
            </Pressable>
          </View>
          {me ? <View style={styles.menuAccount}><Avatar user={me} size={38} /><View style={{ flex: 1 }}>
            <Text style={styles.menuAccountName}>{me.display_name}</Text><Text style={styles.handle}>@{me.username}</Text>
          </View></View> : null}
          <ScrollView keyboardShouldPersistTaps="handled">
            {menuButton("Mini games", () => setScreen("games"))}
            {menuButton("Activities", () => { setScreen("notifications"); void loadNotifications(); }, unreadNotifications)}
            {menuButton("Your profile", () => { void loadProfile(); })}
            {menuButton("Settings & profile tools", () => { void loadSettings(); })}
            {me?.is_moderator ? menuButton("Moderator reports", () => { setScreen("moderation"); void loadModerationReports(); }) : null}
            {menuButton(`Blocked accounts · ${blockedUsers.length}`, async () => { try { setBlockedUsers((await request("/api/blocks")).users); setScreen("blocked"); } catch (e) { fail(e); } })}
            {menuButton("Sign out", () => { void logout(); })}
          </ScrollView>
        </Animated.View>
      </View>
    </Modal>
    <Modal visible={Boolean(selectedImage)} transparent animationType={reduceMotion ? "none" : "fade"} onRequestClose={() => setSelectedImage(null)}>
      <View style={styles.imageModalRoot} accessibilityViewIsModal>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="Close photo viewer"
          onPress={() => setSelectedImage(null)} />
        {selectedImage ? <>
          <Pressable accessibilityRole="button" accessibilityLabel="Close photo viewer"
            onPress={() => setSelectedImage(null)} style={[styles.imageModalClose, { top: insets.top + 12, right: 18 }]}>
            <Text style={styles.imageModalCloseText}>×</Text>
          </Pressable>
          <Image source={{ uri: selectedImage.uri, headers: { Authorization: `Bearer ${token}` } }}
            accessibilityLabel={selectedImage.label} style={styles.imageModalImage} resizeMode="contain" />
        </> : null}
      </View>
    </Modal>
    <Modal visible={!!echoTarget} transparent animationType={reduceMotion ? "none" : "fade"} onRequestClose={() => setEchoTarget(null)}>
      <View style={styles.echoModalRoot}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="Close Echo options"
          onPress={() => setEchoTarget(null)} />
        {echoTarget ? <View style={[styles.echoSheet, { paddingBottom: Math.max(insets.bottom + 12, 24) }]} accessibilityViewIsModal>
          <View style={styles.echoHandle} />
          <Text accessibilityRole="header" style={styles.echoSheetTitle}>Echo</Text>
          <Text style={styles.echoSheetDescription}>Choose how you’d like to share this {echoTarget.type}.</Text>
          <Pressable accessibilityRole="button" onFocus={() => setFocusedEchoOption("echo")} onBlur={() => setFocusedEchoOption(null)}
            onPress={() => chooseEcho("echo")}
            style={({ pressed }) => [styles.echoOption, focusedEchoOption === "echo" && styles.echoOptionFocused, pressed && styles.echoOptionPressed]}>
            <Text style={styles.echoOptionText}>Echo</Text>
          </Pressable>
          <Pressable accessibilityRole="button" onFocus={() => setFocusedEchoOption("thought")} onBlur={() => setFocusedEchoOption(null)}
            onPress={() => chooseEcho("thought")}
            style={({ pressed }) => [styles.echoOption, focusedEchoOption === "thought" && styles.echoOptionFocused, pressed && styles.echoOptionPressed]}>
            <Text style={styles.echoOptionText}>Echo with a thought</Text>
          </Pressable>
          <Pressable accessibilityRole="button" onFocus={() => setFocusedEchoOption("cancel")} onBlur={() => setFocusedEchoOption(null)}
            onPress={() => setEchoTarget(null)}
            style={({ pressed }) => [styles.echoCancel, focusedEchoOption === "cancel" && styles.echoOptionFocused, pressed && styles.echoOptionPressed]}>
            <Text style={styles.echoCancelText}>Cancel</Text>
          </Pressable>
        </View> : null}
      </View>
    </Modal>
    <Modal visible={!!editingContent} transparent animationType={reduceMotion ? "none" : "fade"}
      onRequestClose={() => { setEditingContent(null); setEditingBody(""); }}>
      <View style={styles.editModalRoot} accessibilityViewIsModal>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="Cancel editing"
          onPress={() => { setEditingContent(null); setEditingBody(""); }} />
        {editingContent ? <View style={[styles.editSheet, { backgroundColor: palette.surface, borderColor: palette.border }]}>
          <Text accessibilityRole="header" style={styles.editTitle}>Edit {editingContent.type}</Text>
          <TextInput accessibilityLabel={`Edit ${editingContent.type} text`} accessibilityHint="Existing media and quoted content will remain attached."
            value={editingBody} onChangeText={setEditingBody} multiline maxLength={editingContent.type === "post" ? 5000 : 4000}
            placeholder="Write your text…" placeholderTextColor={palette.muted}
            style={[styles.input, styles.editInput, { backgroundColor: palette.input, borderColor: palette.border, color: "#f5f2ff" }]} />
          <Text style={styles.handle}>{editingBody.length}/{editingContent.type === "post" ? 5000 : 4000}</Text>
          <View style={styles.row}>
            {button("Cancel", () => { setEditingContent(null); setEditingBody(""); }, true)}
            {button("Save changes", () => { void saveEditedContent(); })}
          </View>
        </View> : null}
      </View>
    </Modal>
    <Modal visible={splashVisible} animationType={reduceMotion ? "none" : "fade"} onRequestClose={() => setSplashVisible(false)}>
      <View style={styles.splashScreen} accessibilityViewIsModal>
        <Animated.View style={{ transform: [{ scale: splashGlow.interpolate({ inputRange: [0, 1], outputRange: [0.96, 1.04] }) }] }}>
          <BrandHalo size={108} showLogo />
        </Animated.View>
        <Text style={styles.splashTitle}>ZORLII</Text>
        <Text style={styles.splashSubtitle}>A space to connect</Text>
      </View>
    </Modal>
  </KeyboardAvoidingView>;
}

export default function App() {
  return <SafeAreaProvider><AppContent /></SafeAreaProvider>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: "#070713" },
  authScreenBackground: { backgroundColor: "#070713", backgroundImage: AUTH_PAGE_BACKGROUND_IMAGE },
  authScroll: { backgroundColor: "transparent" },
  scroll: { flex: 1 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, paddingBottom: 13, backgroundColor: "#0b1020", borderBottomWidth: 1, borderBottomColor: "#30264a" },
  menuToggle: { width: 44, height: 44, marginLeft: "auto", borderRadius: 13, alignItems: "center", justifyContent: "center", borderWidth: 1, backgroundColor: "#15172a" },
  menuToggleText: { fontSize: 21, lineHeight: 25, fontWeight: "700" },
  logo: { width: 42, height: 42, borderRadius: 14, backgroundColor: "#17132a" },
  brandHaloWrap: { alignItems: "center", justifyContent: "center", position: "relative", borderWidth: 1, borderColor: "#897b87", shadowColor: "#b69b8a", shadowOpacity: 0.16, shadowRadius: 5, shadowOffset: { width: 0, height: 1 }, elevation: 1 },
  quietBrandHaloWrap: { borderColor: "#51456b", shadowOpacity: 0, elevation: 0 },
  brandHaloRing: { alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: "#ad9aa8", backgroundColor: "#29262e" },
  quietBrandHaloRing: { borderColor: "#625481", backgroundColor: "#201a32" },
  brandCore: { alignItems: "center", justifyContent: "center", overflow: "hidden", backgroundColor: "#17132a" },
  quietBrandCore: { backgroundColor: "#17132a" },
  brandMonogram: { color: "#fbf8ff", fontFamily: "serif", fontWeight: "700" },
  brandPulse: { position: "absolute", top: 3, right: 3, width: 9, height: 9, borderRadius: 5, borderWidth: 1.5, borderColor: "#ead9cb", backgroundColor: "#c59d84" },
  quietBrandPulse: { opacity: 0.55 },
  brand: { color: "#f6f1f8", fontSize: 20, fontWeight: "800", letterSpacing: 2.4, textTransform: "uppercase" }, headerCopy: { flex: 1, flexShrink: 1, minWidth: 0 }, headerSub: { color: "#e5e2ee", fontSize: 12 },
  tabs: { flexDirection: "row", alignItems: "center", justifyContent: "space-around", backgroundColor: "#0b1020", paddingTop: 7, paddingBottom: 8, paddingHorizontal: 4, borderTopWidth: 1, borderTopColor: "#30264a" },
  menuToggleBadge: { position: "absolute", top: -6, right: -7 },
  menuUnreadBadge: { minWidth: 22, height: 22, borderRadius: 11, paddingHorizontal: 6, alignItems: "center", justifyContent: "center" },
  menuUnreadText: { fontSize: 11, lineHeight: 15, fontWeight: "800" },
  tabItem: { width: "20%", minHeight: 53, alignItems: "center", justifyContent: "center", borderRadius: 11, paddingVertical: 3, position: "relative" },
  tabPressed: { backgroundColor: "#21173b" },
  createTab: { alignSelf: "center" },
  tabIcon: { color: "#e5e2ee", fontSize: 19, lineHeight: 24, textAlign: "center", position: "relative", minWidth: 28, height: 28 },
  activeTabIcon: { color: "#d7bcff" },
  createIcon: { color: "#fff", backgroundColor: "#8b35ff", overflow: "hidden", borderRadius: 14, width: 28, height: 28, lineHeight: 27, fontSize: 21 },
  tabBadge: { position: "absolute", top: -1, right: -9, minWidth: 15, height: 15, borderRadius: 8, overflow: "hidden", backgroundColor: "#8b35ff", color: "#fff", fontSize: 9, lineHeight: 15, textAlign: "center", fontWeight: "700" },
  tab: { color: "#e5e2ee", fontSize: 11, fontWeight: "600", textAlign: "center" }, activeTab: { color: "#f5f0ff" },
  content: { paddingHorizontal: 18, paddingTop: 23, paddingBottom: 24, flexGrow: 1 }, form: { marginTop: 16 },
  authContent: { paddingHorizontal: 18, alignItems: "center" },
  authBody: { alignSelf: "center", width: "100%", maxWidth: 440 },
  authIntro: { alignItems: "center", marginBottom: 14 },
  authBrand: { alignItems: "center", marginBottom: 10 },
  authBrandLogo: {
    width: 62, height: 62, borderRadius: 31, borderWidth: 2, borderColor: "#c49bff",
    backgroundColor: "#111329", shadowColor: "#8959ee", shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.62, shadowRadius: 14, elevation: 8,
  },
  authBrandLogoCompact: { width: 54, height: 54, borderRadius: 27 },
  authBrandImage: { width: "100%", height: "100%", borderRadius: 31 },
  authEyebrow: { color: "#cda8ff", fontSize: 11, lineHeight: 17, letterSpacing: 1.76, textTransform: "uppercase", fontWeight: "700", textAlign: "center", includeFontPadding: false, marginBottom: 5 },
  authTitle: { color: "#faf8ff", fontFamily: "serif", fontSize: 30, lineHeight: 34, fontWeight: "700", letterSpacing: -0.9, marginBottom: 6, textAlign: "center", includeFontPadding: false },
  authTitleCompact: { fontSize: 28, lineHeight: 32 },
  authIntroLead: { color: "#f0eafa", fontSize: 14, lineHeight: 20, marginBottom: 5, textAlign: "center", includeFontPadding: false },
  authIntroDescription: { color: "#c9c3d9", fontSize: 12, lineHeight: 17, textAlign: "center", maxWidth: 350, includeFontPadding: false },
  authForm: {
    alignSelf: "stretch", marginTop: 0, marginBottom: 0, padding: 16, borderWidth: 1,
    borderRadius: 18, borderColor: "#453965", backgroundColor: "#111329", backgroundImage: AUTH_CARD_BACKGROUND_IMAGE,
    shadowColor: "#02030c", shadowOffset: { width: 0, height: 18 }, shadowOpacity: 0.4,
    shadowRadius: 24, elevation: 3,
  },
  authFormCompact: { padding: 14 },
  authFormTitle: { color: "#f7f3ff", fontSize: 21, lineHeight: 26, fontWeight: "700", letterSpacing: -0.42, marginBottom: 4, includeFontPadding: false },
  authFormCopy: { color: "#bdb7d0", fontSize: 13, lineHeight: 19.5, marginBottom: 13, includeFontPadding: false },
  authField: { width: "100%", marginTop: 12, marginBottom: 12 },
  authFieldCompact: { marginTop: 9, marginBottom: 9 },
  authFieldLabel: { color: "#e8e2f5", fontSize: 15, lineHeight: 23, fontWeight: "600", includeFontPadding: false },
  authInput: { borderRadius: 9, minHeight: 48, marginVertical: 0, paddingHorizontal: 12, paddingVertical: 11, includeFontPadding: false },
  authActionRow: { flexDirection: "row", alignItems: "stretch", flexWrap: "wrap", columnGap: 12, marginTop: 3 },
  authAction: { minWidth: 140, minHeight: 44, flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "flex-start", gap: 7, paddingVertical: 8, backgroundColor: "transparent" },
  authActionPrimary: { width: "100%", flexBasis: "100%", flexGrow: 0, minHeight: 48, marginTop: 4 },
  authActionText: { color: "#e5d9ff", fontSize: 14, lineHeight: 19, fontWeight: "700", includeFontPadding: false },
  authActionPrimaryText: { fontSize: 16, fontWeight: "800" },
  authActionArrow: { fontSize: 19, fontWeight: "800", includeFontPadding: false },
  authActionDisabled: { opacity: 0.62 },
  pulseHeading: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  refreshButton: { width: 44, height: 44, alignItems: "center", justifyContent: "center", marginBottom: 8, backgroundColor: "transparent" },
  refreshButtonText: { fontSize: 24, lineHeight: 28, fontWeight: "700" },
  settingsPanel: { padding: 14, marginVertical: 9, borderRadius: 15, backgroundColor: "#111329", borderWidth: 1, borderColor: "#393253" },
  colorSwatch: { width: 38, height: 38, borderRadius: 11, borderWidth: 2, borderColor: "#f4f1ff" },
  colorControl: { marginVertical: 2 },
  colorControlLabel: { color: "#e5e2ee", fontSize: 13, fontWeight: "700", marginTop: 5 },
  huePicker: { minHeight: 48, justifyContent: "center", marginVertical: 2 },
  hueSpectrum: { height: 34, flexDirection: "row", borderRadius: 17, overflow: "hidden", position: "relative" },
  hueThumb: { position: "absolute", top: -3, width: 12, height: 40, marginLeft: -6, borderWidth: 3, borderRadius: 7, backgroundColor: "transparent" },
  menuModalRoot: { flex: 1, flexDirection: "row-reverse" },
  menuScrim: { backgroundColor: "#03040bcc" },
  menuDrawer: { maxWidth: 360, height: "100%", paddingHorizontal: 18, backgroundColor: "#101329", borderLeftWidth: 1, borderLeftColor: "#40375e" },
  menuHeading: { minHeight: 52, flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 12 },
  menuTitle: { color: "#f5f2ff", fontSize: 21, fontWeight: "700" },
  menuClose: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: "#49425f", borderRadius: 12, backgroundColor: "#171a2c" },
  menuCloseText: { color: "#f4f1ff", fontSize: 26, lineHeight: 30 },
  menuAccount: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 13, marginBottom: 8, borderTopWidth: 1, borderTopColor: "#302d4d", borderBottomWidth: 1, borderBottomColor: "#302d4d" },
  menuAccountName: { color: "#f4f1ff", fontWeight: "700" },
  menuItem: { minHeight: 48, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 13, marginVertical: 3, borderRadius: 11, borderWidth: 1, borderColor: "#302d4d", backgroundColor: "#15172a" },
  menuItemText: { color: "#ece8f7", fontSize: 15, fontWeight: "600" },
  title: { color: "#faf8ff", fontFamily: "sans-serif", fontSize: 30, fontWeight: "700", letterSpacing: -0.5, marginBottom: 8 },
  eyebrow: { color: "#c28aff", fontSize: 11, letterSpacing: 1.8, textTransform: "uppercase", fontWeight: "700" },
  section: { fontSize: 19, fontFamily: "sans-serif", fontWeight: "700", color: "#eee7f8", marginVertical: 10 },
  copy: { color: "#e5e2ee", lineHeight: 21, marginVertical: 5 }, handle: { color: "#e5e2ee", fontSize: 13 },
  input: { backgroundColor: "#0b0d1d", borderWidth: 1, borderColor: "#41395e", paddingHorizontal: 13, paddingVertical: 12, borderRadius: 12, marginVertical: 6, color: "#f4f1ff", minHeight: 46 },
  passwordFieldRow: { width: "100%", flexDirection: "row", alignItems: "center", gap: 7 },
  passwordInput: { flex: 1, minWidth: 0, width: 0 },
  passwordToggle: { minHeight: 44, minWidth: 58, alignItems: "center", justifyContent: "center", paddingHorizontal: 9, borderWidth: 1, borderRadius: 11 },
  authPasswordToggle: { minHeight: 44, minWidth: 44, alignItems: "center", justifyContent: "center", paddingHorizontal: 8, backgroundColor: "transparent" },
  passwordToggleText: { color: "#f5f2ff", fontWeight: "700" },
  authPasswordToggleText: { fontSize: 14, lineHeight: 19, includeFontPadding: false },
  passwordRequirement: { color: "#c5bfd4", fontSize: 12, marginLeft: 4, lineHeight: 19 },
  passwordRequirementMet: { color: "#8ce0b1" },
  welcomeNote: { borderWidth: 1, borderColor: "#51456b", borderRadius: 16, padding: 16, marginVertical: 12 },
  splashScreen: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: "#080a16" },
  splashTitle: { color: "#f6f1ff", fontSize: 23, fontWeight: "800", letterSpacing: 4, marginTop: 18 },
  splashSubtitle: { color: "#b7a5dc", fontSize: 14, marginTop: 5 },
  composerRow: { flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1, borderRadius: 15, padding: 5, marginVertical: 7 },
  postComposerRow: { alignItems: "flex-end" },
  postComposerInput: { flex: 1, minWidth: 0, minHeight: 44, maxHeight: 104, paddingHorizontal: 10, paddingVertical: 10, textAlignVertical: "center", fontSize: 15 },
  replyInput: { flex: 1, minWidth: 0, minHeight: 44, maxHeight: 44, paddingHorizontal: 10, paddingVertical: 8, fontSize: 15 },
  arrowSubmit: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  arrowSubmitText: { fontSize: 20, fontWeight: "800" },
  mentionSuggestions: { borderWidth: 1, borderRadius: 12, padding: 5, marginBottom: 5, backgroundColor: "#15172a" },
  mentionSuggestion: { minHeight: 44, flexDirection: "row", alignItems: "center", gap: 9, paddingHorizontal: 7, borderRadius: 9 },
  multiline: { minHeight: 82, textAlignVertical: "top" },
  button: { backgroundColor: "#76677b", borderRadius: 11, paddingVertical: 12, paddingHorizontal: 15, marginVertical: 5, alignItems: "center", alignSelf: "flex-start", minWidth: 96, minHeight: 44, justifyContent: "center", shadowColor: "#000000", shadowOpacity: 0.08, shadowRadius: 4, shadowOffset: { width: 0, height: 2 }, elevation: 1 },
  buttonPressed: { opacity: 0.78, transform: [{ scale: 0.985 }] },
  buttonPressedReduced: { opacity: 0.86 },
  buttonText: { color: "white", fontWeight: "700", includeFontPadding: false }, secondary: { backgroundColor: "#17132a", borderWidth: 1, borderColor: "#40335d", shadowOpacity: 0, elevation: 0 }, secondaryText: { color: "#d9c7f5" },
  echoSelected: { backgroundColor: "#281a45", borderColor: "#a855f7" }, echoSelectedText: { color: "#e5cbff" },
  echoModalRoot: { flex: 1, justifyContent: "flex-end", backgroundColor: "#05050dcc" },
  imageModalRoot: { flex: 1, backgroundColor: "#05050df5", alignItems: "center", justifyContent: "center", padding: 18 },
  imageModalImage: { width: "100%", height: "82%" },
  imageModalClose: { position: "absolute", top: 38, right: 20, zIndex: 1, width: 48, height: 48, borderRadius: 24, alignItems: "center", justifyContent: "center", backgroundColor: "#211b31", borderWidth: 1, borderColor: "#615075" },
  imageModalCloseText: { color: "#fff", fontSize: 30, lineHeight: 34 },
  echoSheet: { backgroundColor: "#111329", borderWidth: 1, borderColor: "#7650ad", borderBottomWidth: 0, borderTopLeftRadius: 22, borderTopRightRadius: 22, paddingHorizontal: 20, paddingTop: 12, shadowColor: "#8b35ff", shadowOpacity: 0.24, shadowRadius: 22, shadowOffset: { width: 0, height: -5 }, elevation: 18 },
  echoHandle: { alignSelf: "center", width: 42, height: 4, borderRadius: 2, backgroundColor: "#75628f", marginBottom: 16 },
  echoSheetTitle: { color: "#faf8ff", fontSize: 20, fontWeight: "700" },
  echoSheetDescription: { color: "#aaa7c7", lineHeight: 21, marginTop: 5, marginBottom: 14 },
  echoOption: { width: "100%", minHeight: 50, justifyContent: "center", paddingHorizontal: 15, marginVertical: 5, borderRadius: 12, borderWidth: 1, borderColor: "#40335d", backgroundColor: "#17132a" },
  echoOptionFocused: { borderColor: "#c28aff", backgroundColor: "#281a45" },
  echoOptionPressed: { opacity: 0.76 },
  echoOptionText: { color: "#eee7ff", fontSize: 15, fontWeight: "700" },
  echoCancel: { minHeight: 48, justifyContent: "center", alignItems: "center", marginTop: 5, borderRadius: 12, borderWidth: 1, borderColor: "#302a4d", backgroundColor: "#0b1020" },
  echoCancelText: { color: "#c7bfdc", fontWeight: "600" },
  post: { borderWidth: 1, borderColor: "#342d53", borderRadius: 17, backgroundColor: "#111329", padding: 16, marginVertical: 7, shadowColor: "#31175f", shadowOpacity: 0.22, shadowRadius: 14, shadowOffset: { width: 0, height: 5 }, elevation: 2 }, author: { color: "#f3efff", fontWeight: "700" },
  profileLink: { color: "#d8c2ff", textDecorationLine: "underline" },
  mention: { color: "#d9c0ff", fontWeight: "700" },
  postAuthor: { flexDirection: "row", alignItems: "center", gap: 11, marginBottom: 10 },
  postImage: { width: "100%", height: "100%", backgroundColor: "#070713", borderRadius: 13 },
  singleMedia: { width: "100%", height: 280, backgroundColor: "#070713", borderRadius: 13, overflow: "hidden", marginVertical: 8 },
  mediaGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginVertical: 8 },
  mediaTile: { width: "48%", aspectRatio: 1, backgroundColor: "#070713", borderRadius: 13, overflow: "hidden" },
  gridVideo: { width: "48%", height: 160, backgroundColor: "#070713", borderRadius: 13, overflow: "hidden" },
  postVideo: { width: "100%", height: 240, backgroundColor: "#070713", borderRadius: 13, marginVertical: 8 },
  mediaSelection: { maxHeight: 92, marginVertical: 7 }, mediaSelectionContent: { gap: 8, paddingRight: 4 },
  mediaSelectionItem: { width: 78, height: 78, borderRadius: 12, overflow: "hidden", backgroundColor: "#302b3b", alignItems: "center", justifyContent: "center" },
  mediaSelectionImage: { width: "100%", height: "100%" }, mediaSelectionText: { color: "#e8e1ff", fontSize: 12, fontWeight: "700" },
  mediaPickerButton: { width: 44, height: 44, borderRadius: 14, alignItems: "center", justifyContent: "center", backgroundColor: "#211638", borderWidth: 1, borderColor: "#755aa1", shadowColor: "#8b35ff", shadowOpacity: 0.2, shadowRadius: 7, shadowOffset: { width: 0, height: 2 }, elevation: 2 },
  mediaPickerIcon: { color: "#e6d5ff", fontSize: 22, lineHeight: 26, fontWeight: "400" },
  mediaRemove: { position: "absolute", top: 0, right: 0, width: 44, height: 44, borderRadius: 22, backgroundColor: "#171521cc", alignItems: "center", justifyContent: "center" },
  mediaRemoveText: { color: "#fff", fontSize: 18, lineHeight: 21, fontWeight: "700" },
  avatarHalo: { alignItems: "center", justifyContent: "center", position: "relative", backgroundColor: "#17132a", borderWidth: 2, borderColor: "#8b5fe0" },
  avatar: { alignItems: "center", justifyContent: "center", overflow: "hidden", backgroundColor: "#33224d", borderWidth: 2, borderColor: "#111329" },
  avatarPulse: { position: "absolute", top: 2, right: 2, width: 8, height: 8, borderRadius: 4, borderWidth: 1, borderColor: "#d1b6ff", backgroundColor: "#74d7ff" },
  avatarImage: { width: "100%", height: "100%" }, avatarInitials: { color: "#e6d9ff", fontWeight: "700", fontSize: 16 },
  profileHero: { flexDirection: "row", alignItems: "center", gap: 17, marginBottom: 12, paddingVertical: 8 },
  profileAvatarWrap: { position: "relative" },
  avatarUploadButton: { position: "absolute", right: 0, bottom: 0, width: 34, height: 34, borderRadius: 17, alignItems: "center", justifyContent: "center", backgroundColor: "#8b35ff", borderWidth: 2, borderColor: "#070713", shadowColor: "#8b35ff", shadowOpacity: 0.35, shadowRadius: 7, shadowOffset: { width: 0, height: 2 }, elevation: 4 },
  avatarUploadText: { color: "#fff", fontSize: 25, lineHeight: 29, fontWeight: "500" },
  unreadNotification: { borderLeftWidth: 3, borderLeftColor: "#7da99e", paddingLeft: 12, backgroundColor: "#20212c" },
  relationshipRow: { borderBottomWidth: 1, borderBottomColor: "#373447", paddingVertical: 10 },
  postBody: { color: "#e7e1eb", fontSize: 15, lineHeight: 23, marginVertical: 12 },
  disclosure: { borderWidth: 1, borderColor: "#373447", borderRadius: 14, backgroundColor: "#111329", marginVertical: 6, overflow: "hidden" },
  disclosureTrigger: { minHeight: 54, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 15, paddingVertical: 10 },
  disclosureTitle: { color: "#eee7f8", fontSize: 16, fontWeight: "700", flexShrink: 1 },
  disclosureIcon: { color: "#d2b7ff", fontSize: 24, lineHeight: 28, paddingHorizontal: 5 },
  disclosureContent: { borderTopWidth: 1, borderTopColor: "#302a44", padding: 13 },
  actions: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 5 }, row: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 7, marginVertical: 5 },
  socialAction: { minWidth: 44, minHeight: 44, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, paddingHorizontal: 7, backgroundColor: "transparent" },
  socialActionSelected: { backgroundColor: "transparent" },
  pulseTimeline: { marginLeft: 8, paddingLeft: 18, borderLeftWidth: 1 },
  pulsePost: { borderWidth: 0, borderBottomWidth: 1, borderRadius: 0, marginVertical: 5, paddingHorizontal: 4, shadowOpacity: 0, elevation: 0 },
  pulseNode: { position: "absolute", left: -23, top: 29, width: 9, height: 9, borderRadius: 5, borderWidth: 2 },
  socialActionCount: { fontSize: 12, fontWeight: "600" },
  link: { color: "#c2a8ff", fontWeight: "700", padding: 8 },
  empty: { alignItems: "center", borderWidth: 1, borderStyle: "solid", borderColor: "#494252", borderRadius: 18, padding: 24, marginVertical: 20, backgroundColor: "#191b29" },
  error: { padding: 12, backgroundColor: "#39242f", borderColor: "#805568", borderWidth: 1, borderRadius: 12, marginBottom: 12 }, errorText: { color: "#ffd1dc" },
  checkLine: { padding: 13, marginVertical: 5, backgroundColor: "#191b29", borderRadius: 12, borderWidth: 1, borderColor: "#403b4b" },
  conversationScreen: { flex: 1, minHeight: 0 },
  conversationHeader: { minHeight: 64, flexDirection: "row", alignItems: "center", borderBottomWidth: StyleSheet.hairlineWidth, paddingHorizontal: 10 },
  conversationBack: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  conversationBackText: { fontSize: 36, lineHeight: 40 },
  conversationIdentity: { flex: 1, minWidth: 0, paddingHorizontal: 6 },
  conversationTitle: { color: "#f5f2ff", fontSize: 18, fontWeight: "700" },
  conversationSafety: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  conversationSafetyText: { fontSize: 25, fontWeight: "700" },
  messageList: { flex: 1, minHeight: 0, paddingHorizontal: 16, paddingTop: 10 },
  messageComposer: { minHeight: 56, flexDirection: "row", alignItems: "flex-end", gap: 8, marginHorizontal: 12, marginTop: 8, padding: 6, borderWidth: 1, borderRadius: 18 },
  messageComposerInput: { flex: 1, minHeight: 44, maxHeight: 120, paddingHorizontal: 10, paddingVertical: 10, fontSize: 16, textAlignVertical: "center" },
  conversationDate: { color: "#e5e2ee", fontSize: 12, fontWeight: "700", textAlign: "center", marginBottom: 9 },
  messageScroll: { flex: 1 },
  messageScrollContent: { paddingBottom: 6, flexGrow: 1 },
  loadOlderButton: { minHeight: 44, alignItems: "center", justifyContent: "center", padding: 8, marginBottom: 7, borderRadius: 11, backgroundColor: "#211a31", borderWidth: 1, borderColor: "#493b63" },
  loadOlderText: { color: "#d7c4f4", fontWeight: "700" },
  message: { alignSelf: "flex-start", maxWidth: "92%", padding: 12, backgroundColor: "#292536", borderRadius: 15, marginVertical: 5 },
  myMessage: { alignSelf: "flex-end", backgroundColor: "#233b39" },
  messageAuthor: { color: "#e5e2ee", fontSize: 12, fontWeight: "700", marginBottom: 3 },
  messageBody: { color: "#e7e1eb", lineHeight: 21, flexShrink: 1 },
  messageTime: { color: "#e5e2ee", fontSize: 10, marginTop: 7, alignSelf: "flex-end" },
  replyThread: { borderTopWidth: 1, borderTopColor: "#373447", marginTop: 12, paddingTop: 10 },
  replyCard: { width: "100%", borderWidth: 1, borderColor: "#403b4b", borderRadius: 14, backgroundColor: "#1d1f2c", padding: 13, marginVertical: 7 },
  contentMenuActiveCard: { zIndex: 30, elevation: 4 },
  contentMenuActiveRow: { zIndex: 30 },
  contentMenuAnchor: { position: "relative", zIndex: 8 },
  contentMenuTrigger: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderWidth: 1, borderRadius: 12, backgroundColor: "#15172a" },
  contentMenuDots: { fontSize: 14, letterSpacing: 1, fontWeight: "900" },
  contentMenu: { position: "absolute", left: 0, minWidth: 176, maxHeight: 240, padding: 4, borderWidth: 1, borderRadius: 12, zIndex: 20, elevation: 12, shadowColor: "#000", shadowOpacity: 0.35, shadowRadius: 12, shadowOffset: { width: 0, height: 5 } },
  contentMenuBelow: { top: 42 },
  contentMenuAbove: { bottom: 42 },
  contentMenuButton: { minHeight: 44, justifyContent: "center", paddingHorizontal: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  contentMenuLabel: { color: "#f5f2ff", fontSize: 14, fontWeight: "600" },
  contentMenuDestructive: { color: "#ff9dba" },
  editModalRoot: { flex: 1, justifyContent: "center", alignItems: "center", padding: 20, backgroundColor: "#05040dcc" },
  editSheet: { width: "100%", maxWidth: 520, padding: 18, borderWidth: 1, borderRadius: 18 },
  editTitle: { color: "#f5f2ff", fontSize: 20, fontWeight: "800", marginBottom: 10 },
  editInput: { minHeight: 132, textAlignVertical: "top" },
  quotedItem: { borderWidth: 1, borderColor: "#51495a", borderRadius: 12, padding: 12, marginVertical: 8, backgroundColor: "#151722" },
  quotedOpen: { minHeight: 44, justifyContent: "center" },
  quotedLabel: { color: "#c2a9ce", fontSize: 11, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.8, marginBottom: 6 },
  quotePreview: { borderWidth: 1, borderColor: "#756280", borderRadius: 14, padding: 12, marginVertical: 8, backgroundColor: "#211f2d" },
  repostLabel: { color: "#c28aff", fontSize: 12, fontWeight: "600", marginBottom: 10 },
  memberRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#373447" },
  memberIdentity: { flex: 1, minWidth: 0 },
  threadRow: { flexDirection: "row", alignItems: "center", gap: 12, padding: 13, marginVertical: 4, borderWidth: 1, borderColor: "#373447", borderRadius: 14, backgroundColor: "#191b29" },
  threadOpen: { minHeight: 40, justifyContent: "center", alignSelf: "flex-start", paddingHorizontal: 8 },
  threadOpenText: { color: "#e5e2ee", fontSize: 13, fontWeight: "700" },
  startConversation: { padding: 13, marginVertical: 12, borderWidth: 1, borderColor: "#373447", borderRadius: 15, backgroundColor: "#191b29" },
  countCard: { minWidth: 72, flex: 1, padding: 10, borderRadius: 12, borderWidth: 1, borderColor: "#403b4b", backgroundColor: "#191b29" },
  activityGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 8 },
  activityMetric: { flexBasis: "30%", flexGrow: 1, minWidth: 88, alignItems: "center", paddingVertical: 7 },
  countValue: { color: "#f4eff7", fontSize: 19, fontWeight: "700" },
  countLabel: { color: "#e5e2ee", fontSize: 12, marginTop: 2 },
});

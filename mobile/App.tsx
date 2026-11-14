import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, AppState, Image, KeyboardAvoidingView, Linking, Modal, Platform, Pressable,
  ScrollView, Share, StyleSheet, Text, TextInput, View,
} from "react-native";
import * as SecureStore from "expo-secure-store";
import * as ImagePicker from "expo-image-picker";
import * as Notifications from "expo-notifications";
import Constants from "expo-constants";
import * as Device from "expo-device";
import { VideoView, useVideoPlayer } from "expo-video";
import { StatusBar } from "expo-status-bar";

const API_URL = (process.env.EXPO_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});
type User = { id: number; username: string; email: string; display_name: string; bio: string; avatar_url: string | null; interests: string[]; recommendations_consent: boolean; context_assistance_consent: boolean; terms_accepted: boolean; is_moderator: boolean };
type ReportTarget = { target_type: "post" | "user"; target_id: number; label: string };
type ModerationReport = { id: number; target_type: "post" | "user"; post_id: number | null; target_user_id: number | null; target_username: string | null; reporter_username: string; reason: string; details: string; status: string; created_at: string; post_body: string | null };
type PostMedia = { id: number; url: string; media_type: string };
type Author = { id: number; username: string; display_name: string; avatar_url?: string | null };
type Reply = { id: number; body: string; created_at?: string; reaction_count: number; repost_count: number; reacted: boolean; reposted: boolean; media?: PostMedia[]; quoted_post?: Post | null; quoted_reply?: Reply | null; author: Author };
type Post = { id: number; body: string; created_at: string; reaction_count: number; repost_count: number; reply_count: number; reacted: boolean; reposted: boolean; bookmarked: boolean; reposted_by?: Author | null; quoted_post?: Post | null; quoted_reply?: Reply | null; media?: PostMedia[]; author: Author };
type Conversation = { id: number; last_message?: string; participants: { id: number; username: string; display_name: string; avatar_url?: string | null }[] };
type Member = { id: number; username: string; display_name: string; bio: string; avatar_url?: string | null };
type NotificationItem = { id: number; kind: "follow" | "reply" | "reaction" | "repost" | "quote" | "message" | "reply_reaction" | "reply_repost"; post_id: number | null; created_at: string; read: boolean; actor: Author };
type QuoteTarget = { type: "post" | "reply"; item: Post | Reply };
type NativeFilePart = { uri: string; name: string; type: string };
type NativeUploadFormData = FormData & { append(name: string, value: string | NativeFilePart): void };

function PostVideo({ uri, token }: { uri: string; token: string }) {
  const player = useVideoPlayer(
    { uri, headers: { Authorization: `Bearer ${token}` } },
    instance => { instance.loop = false; },
  );
  return <VideoView style={styles.postVideo} player={player} nativeControls contentFit="contain" />;
}

function passwordPolicyError(password: string) {
  if (password.length < 4 || password.length > 128) return "Use 4–128 characters.";
  if (!/[A-Z]/.test(password)) return "Add at least one uppercase letter.";
  if (!/[a-z]/.test(password)) return "Add at least one lowercase letter.";
  if (!/[0-9]/.test(password)) return "Add at least one number.";
  if (!/[^A-Za-z0-9\s]/.test(password)) return "Add at least one special character.";
  return "";
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
  };
  return descriptions[kind] || "shared an update with you.";
}

function BrandHalo({ size = 48, showLogo = false, quiet = false }: { size?: number; showLogo?: boolean; quiet?: boolean }) {
  return <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
    style={[styles.brandHaloWrap, quiet && styles.quietBrandHaloWrap, { width: size + 14, height: size + 14, borderRadius: (size + 14) / 2 }]}>
    <View style={[styles.brandHaloRing, quiet && styles.quietBrandHaloRing, { width: size + 8, height: size + 8, borderRadius: (size + 8) / 2 }]}>
      <View style={[styles.brandCore, quiet && styles.quietBrandCore, { width: size, height: size, borderRadius: size / 2 }]}>
        {showLogo
          ? <Image source={require("./assets/zorlii-logo.png")} style={[styles.logo, { width: size, height: size, borderRadius: size / 2 }]} resizeMode="contain" />
          : <Text style={[styles.brandMonogram, { fontSize: size * 0.43 }]}>Z</Text>}
      </View>
    </View>
    <View style={[styles.brandPulse, quiet && styles.quietBrandPulse]} />
  </View>;
}

function Avatar({ user, size = 42 }: { user?: { display_name?: string; username?: string; avatar_url?: string | null } | null; size?: number }) {
  const [imageFailed, setImageFailed] = useState(false);
  const name = user?.display_name || user?.username || "Zorlii member";
  const initials = name.trim().split(/\s+/).slice(0, 2).map(part => part[0] || "").join("").toUpperCase() || "Z";
  useEffect(() => { setImageFailed(false); }, [user?.avatar_url]);
  return <View accessible accessibilityRole="image" accessibilityLabel={user?.avatar_url && !imageFailed ? `${name} profile photo` : `${initials} initials`}
    style={[styles.avatarHalo, { width: size + 10, height: size + 10, borderRadius: (size + 10) / 2 }]}>
    <View style={[styles.avatar, { width: size, height: size, borderRadius: size / 2 }]}>
      {user?.avatar_url && !imageFailed
        ? <Image source={{ uri: `${API_URL}${user.avatar_url}` }} style={styles.avatarImage} onError={() => setImageFailed(true)} />
        : <Text style={styles.avatarInitials}>{initials}</Text>}
    </View>
    <View style={styles.avatarPulse} />
  </View>;
}

export default function App() {
  const composerRef = useRef<React.ElementRef<typeof TextInput> | null>(null);
  const pushTokenRef = useRef<string | null>(null);
  const [token, setToken] = useState("");
  const [me, setMe] = useState<User | null>(null);
  const [screen, setScreen] = useState("login");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [posts, setPosts] = useState<Post[]>([]);
  const [postMedia, setPostMedia] = useState<ImagePicker.ImagePickerAsset[]>([]);
  const [replyMedia, setReplyMedia] = useState<ImagePicker.ImagePickerAsset[]>([]);
  const [quoteTarget, setQuoteTarget] = useState<QuoteTarget | null>(null);
  const [echoTarget, setEchoTarget] = useState<QuoteTarget | null>(null);
  const [focusedEchoOption, setFocusedEchoOption] = useState<"echo" | "thought" | "cancel" | null>(null);
  const [profilePosts, setProfilePosts] = useState<Post[]>([]);
  const [replies, setReplies] = useState<Record<number, any[]>>({});
  const [scope, setScope] = useState("all");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [followers, setFollowers] = useState<Member[]>([]);
  const [following, setFollowing] = useState<Member[]>([]);
  const [blockedUsers, setBlockedUsers] = useState<Member[]>([]);
  const [followerCount, setFollowerCount] = useState(0);
  const [followingCount, setFollowingCount] = useState(0);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [search, setSearch] = useState<any>(null);
  const [inboxSearchResults, setInboxSearchResults] = useState<Member[]>([]);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [signupEmail, setSignupEmail] = useState("");
  const [recoveryEmail, setRecoveryEmail] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  const [contextResult, setContextResult] = useState("");
  const [reportTarget, setReportTarget] = useState<ReportTarget | null>(null);
  const [moderationReports, setModerationReports] = useState<ModerationReport[]>([]);
  const reportReturnScreen = useRef("feed");

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
    const response = await fetch(`${API_URL}${path}`, {
      method,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body,
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "Could not upload this media. Please try again.");
    return result;
  }
  function update(key: string, value: string) { setForm(current => ({ ...current, [key]: value })); setError(""); }
  function fail(e: unknown) { setError(e instanceof Error ? e.message : "Something went wrong."); }
  async function registerPushToken(authToken: string) {
    if (!Device.isDevice || (Platform.OS !== "ios" && Platform.OS !== "android")) return false;
    if (pushTokenRef.current) return true;
    const projectId = Constants.easConfig?.projectId || Constants.expoConfig?.extra?.eas?.projectId;
    if (!projectId) throw new Error("Link this app to an EAS project before enabling phone notifications.");
    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("default", {
        name: "Activity alerts",
        importance: Notifications.AndroidImportance.HIGH,
      });
    }
    let permission = await Notifications.getPermissionsAsync();
    if (permission.status !== "granted") permission = await Notifications.requestPermissionsAsync();
    if (permission.status !== "granted") return false;
    const expoToken = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
    const response = await fetch(`${API_URL}/api/push-token`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
      body: JSON.stringify({ token: expoToken, platform: Platform.OS }),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.detail || "Could not register this device for phone notifications.");
    }
    pushTokenRef.current = expoToken;
    return true;
  }
  async function loadFeed(nextScope = scope, silent = false) {
    if (!silent) setLoading(true);
    try { setPosts((await request(`/api/feed?scope=${nextScope}`)).posts); setScope(nextScope); }
    catch (e) { if (!silent) fail(e); } finally { if (!silent) setLoading(false); }
  }
  async function loadInbox() {
    setLoading(true);
    try { setConversations((await request("/api/conversations")).conversations); setScreen("inbox"); }
    catch (e) { fail(e); } finally { setLoading(false); }
  }
  async function loadProfile() {
    setScreen("profile");
    if (!me) return;
    try {
      const [postData, followerData, followingData, blockData] = await Promise.all([
        request(`/api/users/${me.username}/posts`),
        request(`/api/users/${me.username}/followers`),
        request(`/api/users/${me.username}/following`),
        request("/api/blocks"),
      ]);
      setProfilePosts(postData.posts);
      setFollowers(followerData.users);
      setFollowing(followingData.users);
      setBlockedUsers(blockData.users);
      setFollowerCount(followerData.count);
      setFollowingCount(followingData.count);
    }
    catch (e) { fail(e); }
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
        name: asset.fileName || `profile.${contentType.split("/")[1] || "jpg"}`,
        type: contentType,
      });
      await uploadRequest("/api/profile/avatar", body, "PUT");
      setMe((await request("/api/me")).user);
      Alert.alert("Photo updated", "Your profile photo is ready.");
    } catch (e) { fail(e); }
  }
  async function pickPostMedia(forReply = false) {
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
        if (forReply) setReplyMedia(result.assets);
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
          setMe((await request("/api/me")).user);
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
  async function markNotificationRead(id: number) {
    try { await request(`/api/notifications/${id}/read`, "PATCH"); await loadNotifications(); }
    catch (e) { fail(e); }
  }
  async function markAllNotificationsRead() {
    try { await request("/api/notifications/read", "POST"); await loadNotifications(); }
    catch (e) { fail(e); }
  }
  async function toggleReplies(post: Post) {
    if (replies[post.id]) {
      setReplies(current => { const next = { ...current }; delete next[post.id]; return next; });
      return;
    }
    try {
      const result = await request(`/api/posts/${post.id}`);
      setReplies(current => ({ ...current, [post.id]: result.replies }));
      update(`show-reply-${post.id}`, "1");
    } catch (e) { fail(e); }
  }
  async function loadConversation(id: number) {
    try { setConversationId(id); setMessages((await request(`/api/conversations/${id}/messages`)).messages); setScreen("messages"); }
    catch (e) { fail(e); }
  }
  async function acceptTerms() {
    try {
      const result = await request("/api/terms/accept", "POST", { accepted: true });
      setMe(result.user);
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
              setPosts(current => current.filter(item => item.author.id !== person.id));
              Alert.alert("Account blocked", `@${person.username} has been blocked.`);
            } catch (e) { fail(e); }
          } },
        ],
      ) },
      { text: "Cancel", style: "cancel" },
    ]);
  }
  async function enterApp(authToken: string) {
    setToken(authToken);
    await SecureStore.setItemAsync("zorlii_session", authToken);
    try {
      const response = await fetch(`${API_URL}/api/me`, { headers: { Authorization: `Bearer ${authToken}` } });
      if (!response.ok) throw new Error("Please sign in again.");
      const data = await response.json();
      setMe(data.user);
      if (!data.user.terms_accepted) {
        setScreen("terms");
        return;
      }
      const feedResponse = await fetch(`${API_URL}/api/feed?scope=all`, { headers: { Authorization: `Bearer ${authToken}` } });
      if (feedResponse.ok) setPosts((await feedResponse.json()).posts);
      setScreen("feed");
    } catch (e) { await SecureStore.deleteItemAsync("zorlii_session"); setToken(""); fail(e); }
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
      if (active) fail(error);
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
      try {
        const activityData = await request("/api/notifications");
        setUnreadNotifications(activityData.unread_count);
        if (screen === "feed") {
          await loadFeed(scope, true);
          await Promise.all(Object.keys(replies).map(async postId => {
            const result = await request(`/api/posts/${postId}`);
            setReplies(current => ({ ...current, [Number(postId)]: result.replies }));
          }));
        } else if (screen === "notifications") {
          setNotifications(activityData.notifications);
        } else if (screen === "inbox") {
          setConversations((await request("/api/conversations")).conversations);
        } else if (screen === "messages" && conversationId !== null) {
          setMessages((await request(`/api/conversations/${conversationId}/messages`)).messages);
        }
      } catch (e) { fail(e); }
    };
    const stateSubscription = AppState.addEventListener("change", state => {
      if (state === "active") refreshVisibleScreen();
    });
    const interval = setInterval(refreshVisibleScreen, 20000);
    return () => {
      clearInterval(interval);
      stateSubscription.remove();
    };
  }, [token, screen, scope, conversationId, replies]);
  async function submitAuth(register = false) {
    if (register) {
      if (form.accept_terms !== "true") { setError("Confirm that you are 18 or older and accept the Terms of Use and Privacy Policy."); return; }
      const issue = passwordPolicyError(form.password || "");
      if (issue) { setError(issue); return; }
    }
    setLoading(true);
    try {
      if (register) {
        const result = await request("/api/auth/register", "POST", form);
        const email = (form.email || "").trim().toLowerCase();
        setSignupEmail(email);
        setForm(current => ({ ...current, email, password: "", code: "" }));
        setScreen("verify-register");
        setError(result.message);
      } else {
        const data = await request("/api/auth/login", "POST", form);
        await enterApp(data.token);
      }
    } catch (e) { fail(e); } finally { setLoading(false); }
  }
  async function verifyRegistration() {
    setLoading(true);
    try {
      const data = await request("/api/auth/register/verify", "POST", {
        email: signupEmail, code: form.code,
      });
      await enterApp(data.token);
    } catch (e) { fail(e); } finally { setLoading(false); }
  }
  async function logout() {
    const registeredPushToken = pushTokenRef.current;
    pushTokenRef.current = null;
    if (registeredPushToken) {
      try {
        await request("/api/push-token", "DELETE", { token: registeredPushToken, platform: Platform.OS });
      } catch (e) { fail(e); }
    }
    try { await request("/api/auth/logout", "POST"); }
    catch (e) { fail(e); }
    await SecureStore.deleteItemAsync("zorlii_session");
    setToken(""); setMe(null); setScreen("login"); setForm({}); setPostMedia([]);
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
            await SecureStore.deleteItemAsync("zorlii_session");
            setToken(""); setMe(null); setForm({}); setPostMedia([]); setScreen("login");
            setError("Your account and account-owned content have been deleted.");
          } catch (e) { fail(e); }
          finally { setLoading(false); }
        } },
      ],
    );
  }
  async function togglePost(post: Post, action: "reaction" | "bookmark" | "repost") {
    try { await request(`/api/posts/${post.id}/${action}`, "POST"); await loadFeed(); }
    catch (e) { fail(e); }
  }
  async function toggleReply(reply: Reply, action: "reaction" | "repost") {
    try {
      await request(`/api/replies/${reply.id}/${action}`, "POST");
      const current = Object.keys(replies).map(Number);
      await Promise.all(current.map(async postId => {
        const result = await request(`/api/posts/${postId}`);
        setReplies(value => ({ ...value, [postId]: result.replies }));
      }));
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
    if (!bodyText && !replyMedia.length) { setError("Write a reply or add media before sending."); return; }
    try {
      if (replyMedia.length) {
        const body = new FormData() as NativeUploadFormData;
        body.append("body", bodyText);
        replyMedia.forEach((asset, index) => {
          const type = asset.mimeType?.toLowerCase() || "application/octet-stream";
          body.append("media", {
            uri: asset.uri,
            name: asset.fileName || `reply-${index}.${type.split("/")[1] || "bin"}`,
            type,
          });
        });
        await uploadRequest(`/api/posts/${post.id}/replies/media`, body);
      } else {
        await request(`/api/posts/${post.id}/replies`, "POST", { body: bodyText });
      }
      update(`reply-${post.id}`, "");
      setReplyMedia([]);
      const result = await request(`/api/posts/${post.id}`);
      setReplies(current => ({ ...current, [post.id]: result.replies }));
    }
    catch (e) { fail(e); }
  }
  async function startConversation(username: string) {
    try { const data = await request("/api/conversations", "POST", { username }); await loadInbox(); await loadConversation(data.id); }
    catch (e) { fail(e); }
  }
  async function searchInboxMembers() {
    const query = (form.recipient || "").trim();
    if (!query) { setError("Enter a username to find a member."); return; }
    try {
      const result = await request(`/api/search?q=${encodeURIComponent(query)}`);
      setInboxSearchResults(result.people || []);
    } catch (e) { fail(e); }
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
            name: asset.fileName || `media-${index}.${type.split("/")[1] || "bin"}`,
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
    finally { setLoading(false); }
  }

  const field = (name: string, placeholder: string, secure = false, multiline = false) => {
    const profileValue = name === "display_name" ? me?.display_name
      : name === "bio" ? me?.bio : name === "interests" ? me?.interests.join(", ") : undefined;
    return (
    <TextInput accessibilityLabel={placeholder} placeholder={placeholder} placeholderTextColor="#8987a5"
      value={form[name] ?? profileValue ?? ""} onChangeText={value => update(name, value)} secureTextEntry={secure}
      multiline={multiline} keyboardType={name === "code" ? "number-pad" : "default"}
      maxLength={name === "code" ? 6 : name === "password" && (screen === "register" || screen === "reset-code") ? 128 : undefined}
      autoCapitalize="none" style={[styles.input, multiline && styles.multiline]} />
    );
  };
  const button = (label: string, action: () => void, secondary = false) => (
    <Pressable accessibilityRole="button" onPress={action} style={({ pressed }) => [styles.button, secondary && styles.secondary, pressed && styles.buttonPressed]}>
      <Text style={[styles.buttonText, secondary && styles.secondaryText]}>{label}</Text>
    </Pressable>
  );
  const echoButton = (item: Post | Reply, type: "post" | "reply") => (
    <Pressable accessibilityRole="button"
      accessibilityLabel={`Echo options${item.repost_count ? `, ${item.repost_count} echoes` : ""}`}
      accessibilityHint="Choose Echo or Echo with a thought."
      accessibilityState={{ selected: item.reposted }}
      onPress={() => showEchoOptions(item, type)}
      style={({ pressed }) => [styles.button, styles.secondary, item.reposted && styles.echoSelected, pressed && styles.buttonPressed]}>
      <Text style={[styles.buttonText, styles.secondaryText, item.reposted && styles.echoSelectedText]}>
        ↗ Echo{item.repost_count ? ` · ${item.repost_count}` : ""}
      </Text>
    </Pressable>
  );
  const navItems = ["feed", "explore", "create", "inbox", "notifications", "profile"];
  const navLabels: Record<string, string> = {
    feed: "Pulse", explore: "Explore", create: "Create", inbox: "Inbox",
    notifications: "Activities", profile: "You",
  };
  const navIcons: Record<string, string> = {
    feed: "⌂", explore: "⌕", create: "+", inbox: "✉", notifications: "◔", profile: "♙",
  };
  const nav = () => <View style={styles.tabs} accessibilityLabel="Main navigation">
    {navItems.map(item => {
      const selected = screen.startsWith(item) || (item === "profile" && screen.startsWith("social-"))
        || (item === "profile" && screen === "blocked") || (item === "inbox" && screen === "messages");
      const label = item === "notifications" && unreadNotifications
        ? `${navLabels[item]}, ${unreadNotifications} unread`
        : item === "create" ? "Create a post" : navLabels[item];
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
          if (item === "notifications") { setScreen("notifications"); loadNotifications(); }
          if (item === "profile") loadProfile();
        }}>
        <Text style={[styles.tabIcon, selected && styles.activeTabIcon, item === "create" && styles.createIcon]}
          accessibilityElementsHidden>{navIcons[item]}{item === "notifications" && unreadNotifications > 0 ? <Text style={styles.tabBadge}>{unreadNotifications}</Text> : null}</Text>
        <Text style={[styles.tab, selected && styles.activeTab]}>{navLabels[item]}</Text>
      </Pressable>;
    })}
  </View>;
  const mediaContent = (media?: PostMedia[]) => media?.map(item => item.media_type.startsWith("video/")
    ? <PostVideo key={item.id} uri={`${API_URL}${item.url}`} token={token} />
    : <Image key={item.id} source={{ uri: `${API_URL}${item.url}`, headers: { Authorization: `Bearer ${token}` } }} style={styles.postImage} resizeMode="contain" />);
  const quotedContent = (item?: Post | Reply | null, kind = "post") => item ? <View style={styles.quotedItem}>
    <Text style={styles.quotedLabel}>Original {kind} included</Text>
    <View style={styles.postAuthor}><Avatar user={item.author} size={30} /><View><Text style={styles.author}>{item.author.display_name}</Text><Text style={styles.handle}>@{item.author.username}</Text></View></View>
    {item.body ? <Text style={styles.postBody}>{item.body}</Text> : null}
    {mediaContent(item.media)}
  </View> : null;
  const replyCard = (reply: Reply) => <View key={reply.id} style={styles.replyCard}>
    <View style={styles.postAuthor}><Avatar user={reply.author} size={36} /><View style={{ flex: 1 }}><Text style={styles.author}>{reply.author.display_name}</Text><Text style={styles.handle}>@{reply.author.username}</Text></View></View>
    {reply.body ? <Text style={styles.postBody}>{reply.body}</Text> : null}
    {mediaContent(reply.media)}
    {reply.quoted_post ? quotedContent(reply.quoted_post, "post") : null}
    {reply.quoted_reply ? quotedContent(reply.quoted_reply, "reply") : null}
    <View style={styles.actions}>
      {button(`${reply.reacted ? "♥" : "♡"} ${reply.reaction_count ?? 0}`, () => toggleReply(reply, "reaction"), true)}
      {echoButton(reply, "reply")}
      {button("Safety", () => showSafetyOptions(reply.author), true)}
    </View>
  </View>;
  const postCard = (post: Post) => <View key={post.id} style={styles.post}>
    {post.reposted_by ? <Text style={styles.repostLabel}>↗  Echoed by @{post.reposted_by.username}</Text> : null}
    <View style={styles.postAuthor}><Avatar user={post.author} /><View style={{ flex: 1 }}><Text style={styles.author}>{post.author.display_name}</Text><Text style={styles.handle}>@{post.author.username} · {post.created_at}</Text></View></View>
    {post.body ? <Text style={styles.postBody}>{post.body}</Text> : null}
    {mediaContent(post.media)}
    {post.quoted_post ? quotedContent(post.quoted_post, "post") : null}
    {post.quoted_reply ? quotedContent(post.quoted_reply, "reply") : null}
    <View style={styles.actions}>
      {button(`${post.reacted ? "♥" : "♡"} ${post.reaction_count}`, () => togglePost(post, "reaction"), true)}
      {echoButton(post, "post")}
      {button(`Reply · ${post.reply_count}`, () => toggleReplies(post), true)}
      {button(post.bookmarked ? "Saved" : "Save", () => togglePost(post, "bookmark"), true)}
      {button("Safety", () => showSafetyOptions(post.author, post), true)}
    </View>
    {replies[post.id] ? <View style={styles.replyThread}>
      <Text style={styles.section}>Replies</Text>
      {replies[post.id].length ? replies[post.id].map((reply: Reply) => replyCard(reply)) : <Text style={styles.copy}>No replies yet. Start the conversation.</Text>}
      <TextInput accessibilityLabel="Write a thoughtful reply" placeholder="Write a thoughtful reply…" placeholderTextColor="#8987a5"
        value={form[`reply-${post.id}`] || ""} onChangeText={value => update(`reply-${post.id}`, value)}
        multiline style={[styles.input, styles.multiline]} />
      <View style={styles.row}>{button("Add photos or videos", () => pickPostMedia(true), true)}{replyMedia.length ? button("Clear media", () => setReplyMedia([]), true) : null}{button("Send reply", () => sendReply(post))}</View>
      {replyMedia.length ? <ScrollView horizontal style={styles.mediaSelection} contentContainerStyle={styles.mediaSelectionContent}>
        {replyMedia.map((asset, index) => <View key={`${asset.assetId || asset.uri}-${index}`} style={styles.mediaSelectionItem}>
          {asset.type === "video" ? <Text style={styles.mediaSelectionText}>Video</Text> : <Image source={{ uri: asset.uri }} style={styles.mediaSelectionImage} />}
          <Pressable accessibilityRole="button" accessibilityLabel="Remove selected reply media" style={styles.mediaRemove} onPress={() => setReplyMedia(current => current.filter((_, itemIndex) => itemIndex !== index))}><Text style={styles.mediaRemoveText}>×</Text></Pressable>
        </View>)}
      </ScrollView> : null}
    </View> : null}
  </View>;

  function renderBody() {
    if (screen === "terms") return <View style={styles.form}>
      <Text style={styles.title}>A quick community update</Text>
      <Text style={styles.copy}>To continue using Zorlii, confirm that you are at least 18 and accept the Terms of Use and Privacy Policy.</Text>
      {button("Read Terms of Use", () => { void Linking.openURL(`${API_URL}/terms`).catch(fail); }, true)}
      {button("Read Privacy Policy", () => { void Linking.openURL(`${API_URL}/privacy`).catch(fail); }, true)}
      {button("I’m 18+ and accept", acceptTerms)}
      {button("Sign out", logout, true)}
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
      ].map(([value, label]) => <Pressable key={value} accessibilityRole="radio" accessibilityState={{ selected: form.report_reason === value }} style={styles.checkLine} onPress={() => update("report_reason", value)}>
        <Text style={styles.copy}>{form.report_reason === value ? "◉" : "○"}  {label}</Text>
      </Pressable>)}
      {field("report_details", "Additional details (optional)", false, true)}
      {button("Send report", submitReport)}
      {button("Cancel", () => { setReportTarget(null); setScreen(reportReturnScreen.current); }, true)}
    </View>;
    if (screen === "register") return <View style={styles.form}>
      <Text style={styles.title}>Create your account</Text>
      {field("display_name", "Display name")}{field("username", "Username")}{field("email", "Email address")}
      {field("password", "Password (4–128 characters)", true)}
      <Text style={styles.copy}>Include an uppercase letter, a lowercase letter, a number, and a special character.</Text>
      <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: form.accept_terms === "true" }} style={styles.checkLine} onPress={() => update("accept_terms", String(form.accept_terms !== "true"))}>
        <Text style={styles.copy}>{form.accept_terms === "true" ? "☑" : "□"}  I am 18 or older and accept the Terms of Use and Privacy Policy.</Text>
      </Pressable>
      <View style={styles.row}>
        {button("Terms of Use", () => { void Linking.openURL(`${API_URL}/terms`).catch(fail); }, true)}
        {button("Privacy Policy", () => { void Linking.openURL(`${API_URL}/privacy`).catch(fail); }, true)}
      </View>
      {button("Continue to email verification", () => submitAuth(true))}{button("Already joined? Sign in", () => setScreen("login"), true)}
    </View>;
    if (screen === "verify-register") return <View style={styles.form}>
      <Text style={styles.title}>Verify your email</Text>
      <Text style={styles.copy}>If your registration can be verified, a six-digit code may be sent to {signupEmail}. It expires in 10 minutes.</Text>
      {field("code", "Six-digit code")}
      {button("Verify and create account", verifyRegistration)}
      {button("Resend code", async () => {
        try {
          const result = await request("/api/auth/register/resend", "POST", { email: signupEmail });
          setError(result.message);
        } catch (e) { fail(e); }
      }, true)}
      {button("Start again", () => setScreen("register"), true)}
    </View>;
    if (screen === "login") return <View style={styles.form}>
      <Text style={styles.title}>Welcome back</Text>
      {field("email", "Email address")}{field("password", "Password", true)}
      {button("Sign in", () => submitAuth())}
      {button("Create account", () => setScreen("register"), true)}
      {button("Forgot password?", () => setScreen("forgot"), true)}
    </View>;
    if (screen === "forgot") return <View style={styles.form}>
      <Text style={styles.title}>Reset your password</Text>
      <Text style={styles.copy}>If an account exists for the address, we’ll send a one-time code.</Text>
      {field("email", "Email address")}
      {button("Send verification code", async () => {
        try {
          const email = (form.email || "").trim().toLowerCase();
          const result = await request("/api/auth/forgot-password", "POST", { email });
          setRecoveryEmail(email);
          setForm(current => ({ ...current, email, code: "", password: "" }));
          setScreen("reset-code");
          setError(result.message);
        } catch (e) { fail(e); }
      })}
      {button("Back to sign in", () => setScreen("login"), true)}
    </View>;
    if (screen === "reset-code") return <View style={styles.form}>
      <Text style={styles.title}>Choose a new password</Text>
      <Text style={styles.copy}>If {recoveryEmail} belongs to an account, enter the emailed six-digit code. Codes expire in 10 minutes.</Text>
      {field("code", "Six-digit code")}
      {field("password", "New password (4–128 characters)", true)}
      <Text style={styles.copy}>Include an uppercase letter, a lowercase letter, a number, and a special character.</Text>
      {button("Verify code and update password", async () => {
        const issue = passwordPolicyError(form.password || "");
        if (issue) { setError(issue); return; }
        try {
          await request("/api/auth/reset-password", "POST", {
            email: recoveryEmail, code: form.code, password: form.password,
          });
          await SecureStore.deleteItemAsync("zorlii_session");
          setToken(""); setMe(null); setScreen("login");
          setError("Password updated. Sign in with your new password.");
        } catch (e) { fail(e); }
      })}
      {button("Resend code", async () => {
        try {
          const result = await request("/api/auth/forgot-password", "POST", { email: recoveryEmail });
          setError(result.message);
        } catch (e) { fail(e); }
      }, true)}
      {button("Change email", () => setScreen("forgot"), true)}
    </View>;
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
      <Text style={styles.copy}>Updates from members who follow, reply, react, repost, quote, or message you.</Text>
      <View style={styles.row}>
        {button("Refresh", loadNotifications, true)}
        {unreadNotifications ? button("Mark all as read", markAllNotificationsRead, true) : null}
      </View>
      {loading ? <ActivityIndicator color="#a47dff" style={{ margin: 20 }} /> : null}
      {notifications.map(item => <View key={item.id} style={[styles.post, !item.read && styles.unreadNotification]}>
        <View style={styles.postAuthor}><Avatar user={item.actor} size={38} /><View><Text style={styles.author}>{item.actor.display_name}</Text><Text style={styles.handle}>@{item.actor.username}</Text></View></View>
        <Text style={styles.copy}>{activityDescription(item.kind)}</Text>
        <Text style={styles.handle}>{item.created_at}</Text>
        {!item.read ? button("Mark as read", () => markNotificationRead(item.id), true) : <Text style={styles.handle}>Read</Text>}
      </View>)}
      {!loading && !notifications.length ? <View style={styles.empty}><BrandHalo size={54} quiet /><Text style={styles.section}>You’re all caught up.</Text><Text style={styles.copy}>New activity from members will appear here.</Text></View> : null}
    </View>;
    if (screen === "social-followers" || screen === "social-following") {
      const isFollowers = screen === "social-followers";
      const people = isFollowers ? followers : following;
      return <View>
        {button("‹ Profile", loadProfile, true)}
        <Text style={styles.title}>{isFollowers ? "Followers" : "Following"}</Text>
        <Text style={styles.copy}>{isFollowers ? `${followerCount} members follow you.` : `${followingCount} members you follow.`}</Text>
        {people.map(person => <View key={person.id} style={styles.memberRow}>
          <Avatar user={person} size={40} />
          <View style={styles.memberIdentity}><Text style={styles.handle}>@{person.username}</Text><Text style={styles.copy}>{person.display_name}</Text></View>
          {button("Message", () => startConversation(person.username), true)}
        </View>)}
        {!people.length ? <View style={styles.empty}><Text style={styles.section}>{isFollowers ? "No followers yet" : "Not following anyone yet"}</Text><Text style={styles.copy}>Member lists will appear here as your community grows.</Text></View> : null}
      </View>;
    }
    if (screen === "blocked") return <View>
      {button("‹ Profile", loadProfile, true)}
      <Text style={styles.title}>Blocked accounts</Text>
      <Text style={styles.copy}>Members you’ve blocked cannot interact with you through posts, follows, or messages.</Text>
      {blockedUsers.map(person => <View key={person.id} style={styles.memberRow}>
        <Avatar user={person} size={40} />
        <View style={styles.memberIdentity}><Text style={styles.handle}>@{person.username}</Text><Text style={styles.copy}>{person.display_name}</Text></View>
        {button("Unblock", () => unblockUser(person.username), true)}
      </View>)}
      {!blockedUsers.length ? <View style={styles.empty}><Text style={styles.section}>No blocked accounts</Text><Text style={styles.copy}>Your blocked-account list is empty.</Text></View> : null}
    </View>;
    if (screen === "explore") return <View>
      <Text style={styles.title}>Explore</Text><Text style={styles.copy}>Search real member profiles and public posts.</Text>
      {field("query", "Search names, handles, and posts")}
      {button("Search", async () => { try { setSearch(await request(`/api/search?q=${encodeURIComponent((form.query || "").trim())}`)); } catch (e) { fail(e); } })}
      {search ? <View>
        <Text style={styles.section}>People</Text>{search.people.map((person: any) => <View key={person.id} style={styles.post}>
          <View style={styles.postAuthor}><Avatar user={person} /><View><Text style={styles.handle}>@{person.username}</Text><Text style={styles.author}>{person.display_name}</Text></View></View>
          <Text style={styles.copy}>{person.bio || "A Zorlii member"}</Text>{button("Follow", async () => { try { await request(`/api/users/${person.username}/follow`, "POST"); } catch (e) { fail(e); } })}
          {button("Message", () => startConversation(person.username), true)}
          {button("Safety", () => showSafetyOptions(person), true)}
        </View>)}
        <Text style={styles.section}>Public posts</Text>{search.posts.map((post: Post) => postCard(post))}
        {!search.people.length && !search.posts.length ? <Text style={styles.copy}>No matching people or public posts yet.</Text> : null}
      </View> : <Text style={styles.copy}>No search results yet.</Text>}
    </View>;
    if (screen === "inbox") return <View>
      <Text style={styles.title}>Inbox</Text><Text style={styles.copy}>Private messages are visible only to conversation participants.</Text>
      <View style={styles.startConversation}>
        <Text style={styles.section}>Start a conversation</Text>
        {field("recipient", "Search by username")}
        {button("Find members", searchInboxMembers)}
        {inboxSearchResults.map(person => <View key={person.id} style={styles.memberRow}>
          <Avatar user={person} size={40} />
          <View style={styles.memberIdentity}><Text style={styles.handle}>@{person.username}</Text><Text style={styles.copy}>{person.display_name}</Text></View>
          {button("Message", () => startConversation(person.username), true)}
        </View>)}
        {inboxSearchResults.length === 0 && form.recipient ? <Text style={styles.handle}>Search for a member to begin.</Text> : null}
      </View>
      <Text style={styles.section}>Your conversations</Text>
      {conversations.map(c => {
        const person = c.participants.find(participant => participant.id !== me?.id) || c.participants[0];
        return <Pressable key={c.id} accessibilityRole="button" style={styles.threadRow} onPress={() => loadConversation(c.id)}>
          <Avatar user={person} size={42} />
          <View style={styles.memberIdentity}><Text style={styles.author}>{person?.display_name || "Conversation"}</Text><Text style={styles.handle}>@{person?.username || ""}</Text><Text numberOfLines={1} style={styles.copy}>{c.last_message || "No messages yet"}</Text></View>
        </Pressable>;
      })}
      {!conversations.length && <Text style={styles.copy}>Your inbox is quiet. Start a conversation when you’re ready.</Text>}
    </View>;
    if (screen === "messages") return <View>
      {button("‹ Inbox", loadInbox, true)}<Text style={styles.title}>Conversation</Text>
      {(() => { const person = conversations.find(item => item.id === conversationId)?.participants.find(item => item.id !== me?.id); return person ? button("Safety options", () => showSafetyOptions(person), true) : null; })()}
      <View style={styles.messageList}>{messages.map(m => <View key={m.id} style={[styles.message, m.sender_id === me?.id && styles.myMessage]}>
        <Text style={styles.messageAuthor}>{m.sender_id === me?.id ? "You" : `@${m.author.username}`}</Text><Text style={styles.copy}>{m.body}</Text>
      </View>)}</View>
      {field("message", "Write a message", false, true)}
      {button("Send", async () => { try { await request(`/api/conversations/${conversationId}/messages`, "POST", { body: form.message }); update("message", ""); setMessages((await request(`/api/conversations/${conversationId}/messages`)).messages); } catch (e) { fail(e); } })}
    </View>;
    if (screen === "profile") return <View>
      <View style={styles.profileHero}><Avatar user={me} size={88} /><View style={{ flex: 1 }}><Text style={styles.title}>{me?.display_name || "Your profile"}</Text><Text style={styles.handle}>@{me?.username} · {me?.email}</Text></View></View>
      {button(me?.avatar_url ? "Change profile photo" : "Add profile photo", pickAvatar, true)}
      {me?.avatar_url ? button("Remove profile photo", confirmAvatarRemoval, true) : null}
      <Text style={styles.copy}>Your photo appears with your profile and posts.</Text>
      <View style={styles.row}>
        <Pressable accessibilityRole="button" style={styles.countCard} onPress={() => setScreen("social-followers")}><Text style={styles.countValue}>{followerCount}</Text><Text style={styles.copy}>Followers</Text></Pressable>
        <Pressable accessibilityRole="button" style={styles.countCard} onPress={() => setScreen("social-following")}><Text style={styles.countValue}>{followingCount}</Text><Text style={styles.copy}>Following</Text></Pressable>
      </View>
      <Text style={styles.section}>More &amp; account safety</Text>
      <Text style={styles.copy}>Manage member boundaries and safety settings.</Text>
      {button(`Blocked accounts · ${blockedUsers.length}`, () => setScreen("blocked"), true)}
      {field("display_name", "Display name")}{field("bio", "A little about you", false, true)}{field("interests", "Interests, separated by commas")}
      <Text style={styles.section}>Privacy & local tools</Text>
      <Text style={styles.copy}>Both features stay off until you opt in. Recommendations compare real public posts; context help selects supplied sentences. No generative AI is used.</Text>
      <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: form.recommendations_consent ? form.recommendations_consent === "true" : Boolean(me?.recommendations_consent) }} style={styles.checkLine} onPress={() => update("recommendations_consent", String(!(form.recommendations_consent ? form.recommendations_consent === "true" : me?.recommendations_consent)))}><Text>{(form.recommendations_consent ? form.recommendations_consent === "true" : me?.recommendations_consent) ? "☑" : "□"}  Local recommendations from real public posts. No generative AI service.</Text></Pressable>
      <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: form.context_assistance_consent ? form.context_assistance_consent === "true" : Boolean(me?.context_assistance_consent) }} style={styles.checkLine} onPress={() => update("context_assistance_consent", String(!(form.context_assistance_consent ? form.context_assistance_consent === "true" : me?.context_assistance_consent)))}><Text>{(form.context_assistance_consent ? form.context_assistance_consent === "true" : me?.context_assistance_consent) ? "☑" : "□"}  Local extractive context help. Each request needs confirmation; no answer is generated.</Text></Pressable>
      {button("Save profile", async () => { try { const result = await request("/api/profile", "PATCH", {
        display_name: form.display_name || me?.display_name, bio: form.bio ?? me?.bio,
        interests: (form.interests ?? me?.interests.join(",") ?? "").split(",").map(x => x.trim()).filter(Boolean),
        recommendations_consent: form.recommendations_consent ? form.recommendations_consent === "true" : me?.recommendations_consent,
        context_assistance_consent: form.context_assistance_consent ? form.context_assistance_consent === "true" : me?.context_assistance_consent,
      }); setMe(result.user); Alert.alert("Saved", "Your profile and choices have been updated."); } catch (e) { fail(e); } })}
      {me?.recommendations_consent ? <>
        <Text style={styles.section}>Member suggestions</Text>
        <Text style={styles.copy}>A local comparison of opted-in interests and real public posts, not a generative AI service.</Text>
        {button("Find members from real posts", async () => {
          try { setRecommendations((await request("/api/recommendations")).recommendations); }
          catch (e) { fail(e); }
        }, true)}
        {recommendations.map(person => <View key={person.id} style={styles.post}>
          <View style={styles.postAuthor}><Avatar user={person} /><View><Text style={styles.author}>{person.display_name}</Text><Text style={styles.handle}>@{person.username}</Text></View></View>
          <Text style={styles.copy}>{person.bio || "A member sharing public posts."}</Text>
          {button("Follow", async () => { try { await request(`/api/users/${person.username}/follow`, "POST"); } catch (e) { fail(e); } })}
          {button("Message", () => startConversation(person.username), true)}
        </View>)}
        {!recommendations.length ? <Text style={styles.copy}>Suggestions use real public member posts; none may be available yet.</Text> : null}
      </> : null}
      <Text style={styles.section}>Local context help</Text>
      <Text style={styles.copy}>Your text is processed in memory only. Opt in above, then confirm each request.</Text>
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
      <Text style={styles.section}>Phone notifications</Text>
      <Text style={styles.copy}>Get activity alerts when Zorlii is in the background.</Text>
      {button("Enable activity alerts", async () => {
        try {
          const enabled = await registerPushToken(token);
          Alert.alert(
            enabled ? "Activity alerts enabled" : "Notifications are off",
            enabled ? "This device is ready to receive Zorlii activity alerts." : "Allow notifications in your device settings, then try again.",
          );
        } catch (e) { fail(e); }
      }, true)}
      <Text style={styles.section}>Your posts</Text>
      {profilePosts.map(post => postCard(post))}
      {!profilePosts.length ? <Text style={styles.copy}>Your posts will appear here when you share them.</Text> : null}
      <Text style={styles.section}>Your data</Text>
      <Text style={styles.copy}>Export a copy of your account data or permanently close your account.</Text>
      {button("Export my account data", exportAccount, true)}
      {button("Privacy Policy", () => { void Linking.openURL(`${API_URL}/privacy`).catch(fail); }, true)}
      {button("Terms of Use", () => { void Linking.openURL(`${API_URL}/terms`).catch(fail); }, true)}
      {button("Request account deletion online", () => { void Linking.openURL(`${API_URL}/account-deletion`).catch(fail); }, true)}
      {button("Delete account", () => { setForm({}); setScreen("delete-account"); })}
      {button("Sign out", logout, true)}
      {me?.is_moderator ? <>
        <Text style={styles.section}>Moderator reports</Text>
        {button("Refresh open reports", loadModerationReports, true)}
        {moderationReports.map(report => <View key={report.id} style={styles.post}>
          <Text style={styles.author}>{report.target_type === "post" ? "Post" : "Account"} · {report.target_username ? `@${report.target_username}` : "removed content"}</Text>
          {report.post_body ? <Text style={styles.copy}>{report.post_body}</Text> : null}
          <Text style={styles.handle}>Reported by @{report.reporter_username} · {report.reason} · {report.created_at}</Text>
          {report.details ? <Text style={styles.copy}>{report.details}</Text> : null}
          <View style={styles.row}>
            {report.post_id ? button("Remove post", () => removeReportedPost(report), true) : null}
            {button("Mark reviewed", () => updateModerationReport(report.id, "reviewed"), true)}
            {button("Dismiss", () => updateModerationReport(report.id, "dismissed"), true)}
          </View>
        </View>)}
        {!moderationReports.length ? <Text style={styles.copy}>No open reports are currently loaded.</Text> : null}
      </> : null}
    </View>;
    return <View>
      <Text style={styles.eyebrow}>Your community, in focus</Text><Text style={styles.title}>Pulse</Text>
      <View style={styles.row}>{button("Everyone", () => loadFeed("all"), true)}{button("Following", () => loadFeed("following"), true)}{button("Saved", () => loadFeed("bookmarks"), true)}</View>
      <TextInput ref={composerRef} accessibilityLabel="Write a post" placeholder="What would you like to share?" multiline maxLength={5000} value={form.post || ""} onChangeText={value => update("post", value)} style={[styles.input, styles.multiline]} />
      {quoteTarget ? <View style={styles.quotePreview}>
        <Text style={styles.quotedLabel}>Echo with a thought · original {quoteTarget.type}</Text>
        <View style={styles.postAuthor}><Avatar user={quoteTarget.item.author} size={30} /><View><Text style={styles.author}>{quoteTarget.item.author.display_name}</Text><Text style={styles.handle}>@{quoteTarget.item.author.username}</Text></View></View>
        <Text numberOfLines={3} style={styles.copy}>{quoteTarget.item.body || "Media post"}</Text>
        {mediaContent(quoteTarget.item.media)}
        {button("Remove original", () => setQuoteTarget(null), true)}
      </View> : null}
      <View style={styles.row}><Text style={styles.copy}>Visible to: </Text><Pressable onPress={() => update("visibility", form.visibility === "public" ? "followers" : form.visibility === "followers" ? "private" : "public")}><Text style={styles.link}>{form.visibility || "public"} ⌄</Text></Pressable></View>
      <View style={styles.row}>{button("Add photos or videos", pickPostMedia, true)}{postMedia.length ? button("Clear media", () => setPostMedia([]), true) : null}</View>
      {postMedia.length ? <ScrollView horizontal style={styles.mediaSelection} contentContainerStyle={styles.mediaSelectionContent}>
        {postMedia.map((asset, index) => <View key={`${asset.assetId || asset.uri}-${index}`} style={styles.mediaSelectionItem}>
          {asset.type === "video" ? <Text style={styles.mediaSelectionText}>Video</Text> : <Image source={{ uri: asset.uri }} style={styles.mediaSelectionImage} />}
          <Pressable accessibilityRole="button" accessibilityLabel="Remove selected media" style={styles.mediaRemove} onPress={() => setPostMedia(current => current.filter((_, itemIndex) => itemIndex !== index))}><Text style={styles.mediaRemoveText}>×</Text></Pressable>
        </View>)}
      </ScrollView> : null}
      {button("Share thought", sharePost)}
      {loading ? <ActivityIndicator color="#a47dff" style={{ margin: 20 }} /> : posts.map(post => postCard(post))}
      {!loading && posts.length === 0 ? <View style={styles.empty}><BrandHalo size={58} quiet /><Text style={styles.section}>Nothing here just yet.</Text><Text style={styles.copy}>Conversations shared by real Zorlii members will appear here.</Text></View> : null}
    </View>;
  }

  return <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === "ios" ? "padding" : undefined}>
    <StatusBar style="light" />
    <View style={styles.header}><BrandHalo size={42} showLogo /><View style={styles.headerCopy}><Text style={styles.brand}>Zorlii</Text><Text style={styles.headerSub} numberOfLines={1}>A thoughtful little corner</Text></View>
      {me ? <View style={styles.userTag}><Avatar user={me} size={24} /><Text style={styles.userTagText} numberOfLines={1}>@{me.username}</Text></View> : null}</View>
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>
      {error ? <Pressable onPress={() => setError("")} style={styles.error}><Text style={styles.errorText}>{error}  ×</Text></Pressable> : null}
      {loading && screen !== "feed" ? <ActivityIndicator color="#a47dff" /> : null}
      {renderBody()}
    </ScrollView>
    {me?.terms_accepted ? nav() : null}
    <Modal visible={!!echoTarget} transparent animationType="fade" onRequestClose={() => setEchoTarget(null)}>
      <View style={styles.echoModalRoot}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="Close Echo options"
          onPress={() => setEchoTarget(null)} />
        {echoTarget ? <View style={styles.echoSheet} accessibilityViewIsModal>
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
  </KeyboardAvoidingView>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: "#070713" },
  header: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 18, paddingTop: Platform.OS === "ios" ? 57 : 28, paddingBottom: 13, backgroundColor: "#0b1020", borderBottomWidth: 1, borderBottomColor: "#30264a" },
  logo: { width: 42, height: 42, borderRadius: 14, backgroundColor: "#17132a" },
  brandHaloWrap: { alignItems: "center", justifyContent: "center", position: "relative", borderWidth: 1, borderColor: "#8b5fe0", shadowColor: "#8b35ff", shadowOpacity: 0.38, shadowRadius: 10, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  quietBrandHaloWrap: { borderColor: "#51456b", shadowOpacity: 0, elevation: 0 },
  brandHaloRing: { alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: "#b078ff", backgroundColor: "#292044" },
  quietBrandHaloRing: { borderColor: "#625481", backgroundColor: "#201a32" },
  brandCore: { alignItems: "center", justifyContent: "center", overflow: "hidden", backgroundColor: "#17132a" },
  quietBrandCore: { backgroundColor: "#17132a" },
  brandMonogram: { color: "#fbf8ff", fontFamily: "serif", fontWeight: "700" },
  brandPulse: { position: "absolute", top: 3, right: 3, width: 9, height: 9, borderRadius: 5, borderWidth: 1.5, borderColor: "#d1b6ff", backgroundColor: "#74d7ff" },
  quietBrandPulse: { opacity: 0.55 },
  brand: { color: "#f6f1f8", fontSize: 20, fontWeight: "800", letterSpacing: 2.4, textTransform: "uppercase" }, headerCopy: { flexShrink: 1, minWidth: 0 }, headerSub: { color: "#b8b2c3", fontSize: 12 }, userTag: { flexDirection: "row", alignItems: "center", gap: 3, marginLeft: "auto", maxWidth: 110, flexShrink: 1 }, userTagText: { color: "#e9e4ee", fontSize: 11, minWidth: 0, flexShrink: 1 },
  tabs: { flexDirection: "row", alignItems: "center", justifyContent: "space-around", backgroundColor: "#0b1020", paddingTop: 7, paddingBottom: Platform.OS === "ios" ? 24 : 8, paddingHorizontal: 4, borderTopWidth: 1, borderTopColor: "#30264a" },
  tabItem: { width: "16.66%", minHeight: 53, alignItems: "center", justifyContent: "center", borderRadius: 11, paddingVertical: 3, position: "relative" },
  tabPressed: { backgroundColor: "#21173b" },
  createTab: { alignSelf: "center" },
  tabIcon: { color: "#aaa7c7", fontSize: 19, lineHeight: 24, textAlign: "center", position: "relative", minWidth: 28, height: 28 },
  activeTabIcon: { color: "#d7bcff" },
  createIcon: { color: "#fff", backgroundColor: "#8b35ff", overflow: "hidden", borderRadius: 18, width: 36, height: 36, lineHeight: 35, fontSize: 27 },
  tabBadge: { position: "absolute", top: -1, right: -9, minWidth: 15, height: 15, borderRadius: 8, overflow: "hidden", backgroundColor: "#8b35ff", color: "#fff", fontSize: 9, lineHeight: 15, textAlign: "center", fontWeight: "700" },
  tab: { color: "#aaa7c7", fontSize: 11, fontWeight: "600", textAlign: "center" }, activeTab: { color: "#f5f0ff" },
  content: { paddingHorizontal: 18, paddingTop: 23, paddingBottom: 24, flexGrow: 1 }, form: { marginTop: 16 },
  title: { color: "#faf8ff", fontFamily: "sans-serif", fontSize: 30, fontWeight: "700", letterSpacing: -0.5, marginBottom: 8 },
  eyebrow: { color: "#c28aff", fontSize: 11, letterSpacing: 1.8, textTransform: "uppercase", fontWeight: "700" },
  section: { fontSize: 19, fontFamily: "sans-serif", fontWeight: "700", color: "#eee7f8", marginVertical: 10 },
  copy: { color: "#aaa7c7", lineHeight: 21, marginVertical: 5 }, handle: { color: "#aaa7c7", fontSize: 13 },
  input: { backgroundColor: "#0b0d1d", borderWidth: 1, borderColor: "#41395e", paddingHorizontal: 13, paddingVertical: 12, borderRadius: 12, marginVertical: 6, color: "#f4f1ff", minHeight: 46 },
  multiline: { minHeight: 82, textAlignVertical: "top" },
  button: { backgroundColor: "#843ef1", borderRadius: 11, paddingVertical: 12, paddingHorizontal: 15, marginVertical: 5, alignItems: "center", alignSelf: "flex-start", minWidth: 96, minHeight: 44, justifyContent: "center", shadowColor: "#8b35ff", shadowOpacity: 0.24, shadowRadius: 9, shadowOffset: { width: 0, height: 3 }, elevation: 2 },
  buttonPressed: { opacity: 0.78, transform: [{ scale: 0.985 }] },
  buttonText: { color: "white", fontWeight: "700" }, secondary: { backgroundColor: "#17132a", borderWidth: 1, borderColor: "#40335d", shadowOpacity: 0, elevation: 0 }, secondaryText: { color: "#d9c7f5" },
  echoSelected: { backgroundColor: "#281a45", borderColor: "#a855f7" }, echoSelectedText: { color: "#e5cbff" },
  echoModalRoot: { flex: 1, justifyContent: "flex-end", backgroundColor: "#05050dcc" },
  echoSheet: { backgroundColor: "#111329", borderWidth: 1, borderColor: "#7650ad", borderBottomWidth: 0, borderTopLeftRadius: 22, borderTopRightRadius: 22, paddingHorizontal: 20, paddingTop: 12, paddingBottom: Platform.OS === "ios" ? 34 : 24, shadowColor: "#8b35ff", shadowOpacity: 0.24, shadowRadius: 22, shadowOffset: { width: 0, height: -5 }, elevation: 18 },
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
  postAuthor: { flexDirection: "row", alignItems: "center", gap: 11, marginBottom: 10 },
  postImage: { width: "100%", height: 280, backgroundColor: "#070713", borderRadius: 13, marginVertical: 8 },
  postVideo: { width: "100%", height: 240, backgroundColor: "#070713", borderRadius: 13, marginVertical: 8 },
  mediaSelection: { maxHeight: 92, marginVertical: 7 }, mediaSelectionContent: { gap: 8, paddingRight: 4 },
  mediaSelectionItem: { width: 78, height: 78, borderRadius: 12, overflow: "hidden", backgroundColor: "#302b3b", alignItems: "center", justifyContent: "center" },
  mediaSelectionImage: { width: "100%", height: "100%" }, mediaSelectionText: { color: "#e8e1ff", fontSize: 12, fontWeight: "700" },
  mediaRemove: { position: "absolute", top: 3, right: 3, width: 30, height: 30, borderRadius: 15, backgroundColor: "#171521", alignItems: "center", justifyContent: "center" },
  mediaRemoveText: { color: "#fff", fontSize: 18, lineHeight: 21, fontWeight: "700" },
  avatarHalo: { alignItems: "center", justifyContent: "center", position: "relative", backgroundColor: "#17132a", borderWidth: 2, borderColor: "#8b5fe0" },
  avatar: { alignItems: "center", justifyContent: "center", overflow: "hidden", backgroundColor: "#33224d", borderWidth: 2, borderColor: "#111329" },
  avatarPulse: { position: "absolute", top: 2, right: 2, width: 8, height: 8, borderRadius: 4, borderWidth: 1, borderColor: "#d1b6ff", backgroundColor: "#74d7ff" },
  avatarImage: { width: "100%", height: "100%" }, avatarInitials: { color: "#e6d9ff", fontWeight: "700", fontSize: 16 },
  profileHero: { flexDirection: "row", alignItems: "center", gap: 17, marginBottom: 12, paddingVertical: 8 },
  unreadNotification: { borderLeftWidth: 3, borderLeftColor: "#7da99e", paddingLeft: 12, backgroundColor: "#20212c" },
  relationshipRow: { borderBottomWidth: 1, borderBottomColor: "#373447", paddingVertical: 10 },
  postBody: { color: "#e7e1eb", fontSize: 15, lineHeight: 23, marginVertical: 12 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 6 }, row: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 7, marginVertical: 5 },
  link: { color: "#c2a8ff", fontWeight: "700", padding: 8 },
  empty: { alignItems: "center", borderWidth: 1, borderStyle: "solid", borderColor: "#494252", borderRadius: 18, padding: 24, marginVertical: 20, backgroundColor: "#191b29" },
  error: { padding: 12, backgroundColor: "#39242f", borderColor: "#805568", borderWidth: 1, borderRadius: 12, marginBottom: 12 }, errorText: { color: "#ffd1dc" },
  checkLine: { padding: 13, marginVertical: 5, backgroundColor: "#191b29", borderRadius: 12, borderWidth: 1, borderColor: "#403b4b" },
  messageList: { minHeight: 180, maxHeight: 420, backgroundColor: "#151724", padding: 12, borderRadius: 16, borderWidth: 1, borderColor: "#373447", marginVertical: 12 },
  message: { alignSelf: "flex-start", maxWidth: "86%", padding: 12, backgroundColor: "#292536", borderRadius: 15, marginVertical: 5 },
  myMessage: { alignSelf: "flex-end", backgroundColor: "#233b39" },
  messageAuthor: { color: "#d4c7dc", fontSize: 12, fontWeight: "700", marginBottom: 3 },
  replyThread: { borderTopWidth: 1, borderTopColor: "#373447", marginTop: 12, paddingTop: 10 },
  replyCard: { width: "100%", borderWidth: 1, borderColor: "#403b4b", borderRadius: 14, backgroundColor: "#1d1f2c", padding: 13, marginVertical: 7 },
  quotedItem: { borderWidth: 1, borderColor: "#51495a", borderRadius: 12, padding: 12, marginVertical: 8, backgroundColor: "#151722" },
  quotedLabel: { color: "#c2a9ce", fontSize: 11, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.8, marginBottom: 6 },
  quotePreview: { borderWidth: 1, borderColor: "#756280", borderRadius: 14, padding: 12, marginVertical: 8, backgroundColor: "#211f2d" },
  repostLabel: { color: "#c28aff", fontSize: 12, fontWeight: "600", marginBottom: 10 },
  memberRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#373447" },
  memberIdentity: { flex: 1, minWidth: 0 },
  threadRow: { flexDirection: "row", alignItems: "center", gap: 12, padding: 13, marginVertical: 4, borderWidth: 1, borderColor: "#373447", borderRadius: 14, backgroundColor: "#191b29" },
  startConversation: { padding: 13, marginVertical: 12, borderWidth: 1, borderColor: "#373447", borderRadius: 15, backgroundColor: "#191b29" },
  countCard: { minWidth: 120, flex: 1, padding: 14, borderRadius: 14, borderWidth: 1, borderColor: "#403b4b", backgroundColor: "#191b29" },
  countValue: { color: "#f4eff7", fontSize: 21, fontWeight: "700" },
});

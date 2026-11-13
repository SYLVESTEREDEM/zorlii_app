import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Image, KeyboardAvoidingView, Platform, Pressable,
  ScrollView, Share, StyleSheet, Text, TextInput, View,
} from "react-native";
import * as SecureStore from "expo-secure-store";
import * as ImagePicker from "expo-image-picker";
import { StatusBar } from "expo-status-bar";

const API_URL = (process.env.EXPO_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
type User = { id: number; username: string; email: string; display_name: string; bio: string; avatar_url: string | null; interests: string[]; recommendations_consent: boolean; context_assistance_consent: boolean };
type Post = { id: number; body: string; created_at: string; reaction_count: number; reply_count: number; reacted: boolean; bookmarked: boolean; author: { id: number; username: string; display_name: string; avatar_url?: string | null } };
type Conversation = { id: number; last_message?: string; participants: { id: number; username: string; display_name: string; avatar_url?: string | null }[] };
type Member = { id: number; username: string; display_name: string; bio: string; avatar_url?: string | null };
type NotificationItem = { id: number; kind: "follow" | "reply" | "reaction"; post_id: number | null; created_at: string; read: boolean; actor: { username: string; display_name: string; avatar_url?: string | null } };

function passwordPolicyError(password: string) {
  if (password.length < 4 || password.length > 128) return "Use 4–128 characters.";
  if (!/[A-Z]/.test(password)) return "Add at least one uppercase letter.";
  if (!/[a-z]/.test(password)) return "Add at least one lowercase letter.";
  if (!/[0-9]/.test(password)) return "Add at least one number.";
  if (!/[^A-Za-z0-9\s]/.test(password)) return "Add at least one special character.";
  return "";
}

function BrandHalo({ size = 48, showLogo = false }: { size?: number; showLogo?: boolean }) {
  return <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants"
    style={[styles.brandHaloWrap, { width: size + 14, height: size + 14, borderRadius: (size + 14) / 2 }]}>
    <View style={[styles.brandHaloRing, { width: size + 8, height: size + 8, borderRadius: (size + 8) / 2 }]}>
      <View style={[styles.brandCore, { width: size, height: size, borderRadius: size / 2 }]}>
        {showLogo
          ? <Image source={require("./assets/zorlii-logo.png")} style={[styles.logo, { width: size, height: size, borderRadius: size / 2 }]} resizeMode="contain" />
          : <Text style={[styles.brandMonogram, { fontSize: size * 0.43 }]}>Z</Text>}
      </View>
    </View>
    <View style={styles.brandPulse} />
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
  const [token, setToken] = useState("");
  const [me, setMe] = useState<User | null>(null);
  const [screen, setScreen] = useState("login");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [posts, setPosts] = useState<Post[]>([]);
  const [profilePosts, setProfilePosts] = useState<Post[]>([]);
  const [replies, setReplies] = useState<Record<number, any[]>>({});
  const [scope, setScope] = useState("all");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [followers, setFollowers] = useState<Member[]>([]);
  const [following, setFollowing] = useState<Member[]>([]);
  const [followerCount, setFollowerCount] = useState(0);
  const [followingCount, setFollowingCount] = useState(0);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [search, setSearch] = useState<any>(null);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [signupEmail, setSignupEmail] = useState("");
  const [recoveryEmail, setRecoveryEmail] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  const [contextResult, setContextResult] = useState("");

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
  function update(key: string, value: string) { setForm(current => ({ ...current, [key]: value })); setError(""); }
  function fail(e: unknown) { setError(e instanceof Error ? e.message : "Something went wrong."); }
  async function loadFeed(nextScope = scope) {
    setLoading(true);
    try { setPosts((await request(`/api/feed?scope=${nextScope}`)).posts); setScope(nextScope); }
    catch (e) { fail(e); } finally { setLoading(false); }
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
      const [postData, followerData, followingData] = await Promise.all([
        request(`/api/users/${me.username}/posts`),
        request(`/api/users/${me.username}/followers`),
        request(`/api/users/${me.username}/following`),
      ]);
      setProfilePosts(postData.posts);
      setFollowers(followerData.users);
      setFollowing(followingData.users);
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
        mediaTypes: ["images"], allowsEditing: true, aspect: [1, 1], quality: 0.85, base64: true,
      });
      if (result.canceled) return;
      const asset = result.assets[0];
      const contentType = asset.mimeType?.toLowerCase() || "image/jpeg";
      if (!["image/jpeg", "image/png", "image/webp"].includes(contentType)) {
        throw new Error("Choose a JPEG, PNG, or WebP image.");
      }
      if ((asset.fileSize && asset.fileSize > 2 * 1024 * 1024)
        || (asset.base64 && asset.base64.length > Math.ceil((2 * 1024 * 1024) * 4 / 3))) {
        throw new Error("Profile photos must be 2 MB or smaller.");
      }
      if (!asset.base64) throw new Error("Could not read that photo. Please choose another.");
      await request("/api/profile/avatar", "PUT", {
        content_type: contentType, image_base64: asset.base64,
      });
      setMe((await request("/api/me")).user);
      Alert.alert("Photo updated", "Your profile photo is ready.");
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
  async function enterApp(authToken: string) {
    setToken(authToken);
    await SecureStore.setItemAsync("zorlii_session", authToken);
    try {
      const response = await fetch(`${API_URL}/api/me`, { headers: { Authorization: `Bearer ${authToken}` } });
      if (!response.ok) throw new Error("Please sign in again.");
      const data = await response.json();
      setMe(data.user);
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
  useEffect(() => { if (token) loadNotifications(); }, [token]);
  async function submitAuth(register = false) {
    if (register) {
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
    try { await request("/api/auth/logout", "POST"); } catch { }
    await SecureStore.deleteItemAsync("zorlii_session");
    setToken(""); setMe(null); setScreen("login"); setForm({});
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
            setToken(""); setMe(null); setForm({}); setScreen("login");
            setError("Your account and account-owned content have been deleted.");
          } catch (e) { fail(e); }
          finally { setLoading(false); }
        } },
      ],
    );
  }
  async function togglePost(post: Post, action: "reaction" | "bookmark") {
    try { await request(`/api/posts/${post.id}/${action}`, "POST"); await loadFeed(); }
    catch (e) { fail(e); }
  }
  async function sendReply(post: Post) {
    try { await request(`/api/posts/${post.id}/replies`, "POST", { body: form[`reply-${post.id}`] }); update(`reply-${post.id}`, ""); await loadFeed(); }
    catch (e) { fail(e); }
  }
  async function startConversation(username: string) {
    try { const data = await request("/api/conversations", "POST", { username }); await loadInbox(); await loadConversation(data.id); }
    catch (e) { fail(e); }
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
    <Pressable accessibilityRole="button" onPress={action} style={[styles.button, secondary && styles.secondary]}>
      <Text style={[styles.buttonText, secondary && styles.secondaryText]}>{label}</Text>
    </Pressable>
  );
  const navItems = ["feed", "explore", "create", "inbox", "notifications", "profile"];
  const navLabels: Record<string, string> = {
    feed: "Pulse", explore: "Explore", create: "Create", inbox: "Inbox",
    notifications: "Alerts", profile: "You",
  };
  const navIcons: Record<string, string> = {
    feed: "⌂", explore: "⌕", create: "+", inbox: "✉", notifications: "◔", profile: "♙",
  };
  const nav = () => <View style={styles.tabs} accessibilityLabel="Main navigation">
    {navItems.map(item => {
      const selected = screen.startsWith(item);
      const label = item === "notifications" && unreadNotifications
        ? `${navLabels[item]}, ${unreadNotifications} unread`
        : item === "create" ? "Create a post" : navLabels[item];
      return <Pressable key={item} accessibilityRole="button" accessibilityLabel={label}
        accessibilityState={{ selected }} style={[styles.tabItem, item === "create" && styles.createTab]}
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
  const postCard = (post: Post) => <View key={post.id} style={styles.post}>
    <View style={styles.postAuthor}><Avatar user={post.author} /><View><Text style={styles.author}>{post.author.display_name}</Text><Text style={styles.handle}>@{post.author.username}</Text></View></View>
    <Text style={styles.postBody}>{post.body}</Text>
    <View style={styles.actions}>
      {button(`${post.reacted ? "♥" : "♡"} ${post.reaction_count}`, () => togglePost(post, "reaction"), true)}
      {button(post.bookmarked ? "Saved" : "Save", () => togglePost(post, "bookmark"), true)}
      {button(`Reply · ${post.reply_count}`, () => toggleReplies(post), true)}
      {button("Message", () => startConversation(post.author.username), true)}
    </View>
    {replies[post.id] ? <View>{replies[post.id].map(reply => <Text key={reply.id} style={styles.copy}><Text style={styles.author}>@{reply.author.username} </Text>{reply.body}</Text>)}{field(`reply-${post.id}`, "Write a thoughtful reply")} {button("Send reply", () => sendReply(post))}</View> : null}
  </View>;

  function renderBody() {
    if (screen === "register") return <View style={styles.form}>
      <Text style={styles.title}>Create your account</Text>
      {field("display_name", "Display name")}{field("username", "Username")}{field("email", "Email address")}
      {field("password", "Password (4–128 characters)", true)}
      <Text style={styles.copy}>Include an uppercase letter, a lowercase letter, a number, and a special character.</Text>
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
      <Text style={styles.title}>Notifications</Text>
      <Text style={styles.copy}>Updates from real members who follow, reply to, or react to your posts.</Text>
      <View style={styles.row}>
        {button("Refresh", loadNotifications, true)}
        {unreadNotifications ? button("Mark all as read", markAllNotificationsRead, true) : null}
      </View>
      {loading ? <ActivityIndicator color="#a47dff" style={{ margin: 20 }} /> : null}
      {notifications.map(item => <View key={item.id} style={[styles.post, !item.read && styles.unreadNotification]}>
        <View style={styles.postAuthor}><Avatar user={item.actor} size={38} /><View><Text style={styles.author}>{item.actor.display_name}</Text><Text style={styles.handle}>@{item.actor.username}</Text></View></View>
        <Text style={styles.copy}>{item.kind === "follow" ? "started following you." : item.kind === "reply" ? "replied to your post." : "reacted to your post."}</Text>
        <Text style={styles.handle}>{item.created_at}</Text>
        {!item.read ? button("Mark as read", () => markNotificationRead(item.id), true) : <Text style={styles.handle}>Read</Text>}
      </View>)}
      {!loading && !notifications.length ? <View style={styles.empty}><BrandHalo size={54} /><Text style={styles.section}>You’re all caught up.</Text><Text style={styles.copy}>New activity from members will appear here.</Text></View> : null}
    </View>;
    if (screen === "explore") return <View>
      <Text style={styles.title}>Explore</Text><Text style={styles.copy}>Search real member profiles and public posts.</Text>
      {field("query", "Search names, handles, and posts")}
      {button("Search", async () => { try { setSearch(await request(`/api/search?q=${encodeURIComponent(form.query || "")}`)); } catch (e) { fail(e); } })}
      {search ? <View>
        <Text style={styles.section}>People</Text>{search.people.map((person: any) => <View key={person.id} style={styles.post}>
          <View style={styles.postAuthor}><Avatar user={person} /><View><Text style={styles.author}>{person.display_name}</Text><Text style={styles.handle}>@{person.username}</Text></View></View>
          <Text style={styles.copy}>{person.bio || "A Zorlii member"}</Text>{button("Follow", async () => { try { await request(`/api/users/${person.username}/follow`, "POST"); } catch (e) { fail(e); } })}
          {button("Message", () => startConversation(person.username), true)}
        </View>)}
        <Text style={styles.section}>Public posts</Text>{search.posts.map((post: Post) => postCard(post))}
        {!search.people.length && !search.posts.length ? <Text style={styles.copy}>No matching people or public posts yet.</Text> : null}
      </View> : <Text style={styles.copy}>No search results yet.</Text>}
    </View>;
    if (screen === "inbox") return <View>
      <Text style={styles.title}>Inbox</Text><Text style={styles.copy}>Private messages are visible only to conversation participants.</Text>
      {field("recipient", "Start with a username")}{button("Start conversation", () => startConversation(form.recipient || ""))}
      {conversations.map(c => <Pressable key={c.id} style={styles.post} onPress={() => loadConversation(c.id)}>
        <View style={styles.postAuthor}>{c.participants.slice(0, 1).map(person => <Avatar key={person.id} user={person} size={38} />)}<View><Text style={styles.author}>{c.participants.map(p => p.display_name).join(", ")}</Text><Text style={styles.copy}>{c.last_message || "No messages yet"}</Text></View></View>
      </Pressable>)}
      {!conversations.length && <Text style={styles.copy}>Your inbox is quiet. Start a conversation when you’re ready.</Text>}
    </View>;
    if (screen === "messages") return <View>
      {button("‹ Inbox", loadInbox, true)}<Text style={styles.title}>Conversation</Text>
      <View style={styles.messageList}>{messages.map(m => <View key={m.id} style={styles.message}>
        <View style={styles.postAuthor}><Avatar user={m.author} size={32} /><Text style={styles.author}>{m.author.display_name}</Text></View><Text style={styles.copy}>{m.body}</Text>
      </View>)}</View>
      {field("message", "Write a message", false, true)}
      {button("Send", async () => { try { await request(`/api/conversations/${conversationId}/messages`, "POST", { body: form.message }); update("message", ""); setMessages((await request(`/api/conversations/${conversationId}/messages`)).messages); } catch (e) { fail(e); } })}
    </View>;
    if (screen === "profile") return <View>
      <View style={styles.profileHero}><Avatar user={me} size={88} /><View style={{ flex: 1 }}><Text style={styles.title}>{me?.display_name || "Your profile"}</Text><Text style={styles.handle}>@{me?.username} · {me?.email}</Text></View></View>
      {button(me?.avatar_url ? "Change profile photo" : "Add profile photo", pickAvatar, true)}
      {me?.avatar_url ? button("Remove profile photo", confirmAvatarRemoval, true) : null}
      <Text style={styles.copy}>Choose a JPEG, PNG, or WebP image up to 2 MB. Your photo appears with your profile and posts.</Text>
      <View style={styles.row}><Text style={styles.copy}>{followerCount} followers</Text><Text style={styles.copy}>{followingCount} following</Text></View>
      <Text style={styles.section}>Followers</Text>
      {followers.map(person => <View key={person.id} style={styles.relationshipRow}>
        <View style={styles.postAuthor}><Avatar user={person} size={36} /><View><Text style={styles.author}>{person.display_name}</Text><Text style={styles.handle}>@{person.username}</Text></View></View>
        {person.bio ? <Text style={styles.copy}>{person.bio}</Text> : null}
      </View>)}
      {!followers.length ? <Text style={styles.copy}>No followers yet.</Text> : null}
      <Text style={styles.section}>Following</Text>
      {following.map(person => <View key={person.id} style={styles.relationshipRow}>
        <View style={styles.postAuthor}><Avatar user={person} size={36} /><View><Text style={styles.author}>{person.display_name}</Text><Text style={styles.handle}>@{person.username}</Text></View></View>
        {person.bio ? <Text style={styles.copy}>{person.bio}</Text> : null}
      </View>)}
      {!following.length ? <Text style={styles.copy}>You’re not following anyone yet.</Text> : null}
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
      <Text style={styles.section}>Your posts</Text>
      {profilePosts.map(post => postCard(post))}
      {!profilePosts.length ? <Text style={styles.copy}>Your posts will appear here when you share them.</Text> : null}
      <Text style={styles.section}>Your data</Text>
      <Text style={styles.copy}>Export a copy of your account data or permanently close your account.</Text>
      {button("Export my account data", exportAccount, true)}
      {button("Delete account", () => { setForm({}); setScreen("delete-account"); })}
      {button("Sign out", logout, true)}
    </View>;
    return <View>
      <Text style={styles.eyebrow}>Your community, in focus</Text><Text style={styles.title}>Pulse</Text>
      <View style={styles.row}>{button("Everyone", () => loadFeed("all"), true)}{button("Following", () => loadFeed("following"), true)}{button("Saved", () => loadFeed("bookmarks"), true)}</View>
      <TextInput ref={composerRef} accessibilityLabel="Write a post" placeholder="What would you like to share?" multiline maxLength={5000} value={form.post || ""} onChangeText={value => update("post", value)} style={[styles.input, styles.multiline]} />
      <View style={styles.row}><Text style={styles.copy}>Visible to: </Text><Pressable onPress={() => update("visibility", form.visibility === "public" ? "followers" : form.visibility === "followers" ? "private" : "public")}><Text style={styles.link}>{form.visibility || "public"} ⌄</Text></Pressable></View>
      {button("Share thought", async () => { try { await request("/api/posts", "POST", { body: form.post, visibility: form.visibility || "public" }); update("post", ""); await loadFeed(); } catch (e) { fail(e); } })}
      {loading ? <ActivityIndicator color="#a47dff" style={{ margin: 20 }} /> : posts.map(post => postCard(post))}
      {!loading && posts.length === 0 ? <View style={styles.empty}><BrandHalo size={58} /><Text style={styles.section}>Nothing here just yet.</Text><Text style={styles.copy}>Conversations shared by real Zorlii members will appear here.</Text></View> : null}
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
    {me ? nav() : null}
  </KeyboardAvoidingView>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: "#080a16" },
  header: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 18, paddingTop: Platform.OS === "ios" ? 57 : 28, paddingBottom: 13, backgroundColor: "#0c1022", borderBottomWidth: 1, borderBottomColor: "#393054" },
  logo: { width: 42, height: 42, borderRadius: 14, backgroundColor: "#15152d" },
  brandHaloWrap: { alignItems: "center", justifyContent: "center", position: "relative", borderWidth: 1, borderColor: "#9674f7aa", shadowColor: "#9364ff", shadowOpacity: 0.5, shadowRadius: 12, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  brandHaloRing: { alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: "#b69aff", backgroundColor: "#30205a" },
  brandCore: { alignItems: "center", justifyContent: "center", overflow: "hidden", backgroundColor: "#17162e" },
  brandMonogram: { color: "#fbf8ff", fontFamily: "serif", fontWeight: "700" },
  brandPulse: { position: "absolute", top: 3, right: 3, width: 9, height: 9, borderRadius: 5, borderWidth: 1.5, borderColor: "#d8f6ff", backgroundColor: "#78d8ff", shadowColor: "#65caff", shadowOpacity: 0.9, shadowRadius: 7, elevation: 4 },
  brand: { color: "#fff", fontSize: 20, fontWeight: "800", letterSpacing: 2.4, textTransform: "uppercase" }, headerCopy: { flexShrink: 1, minWidth: 0 }, headerSub: { color: "#aaa8c5", fontSize: 12 }, userTag: { flexDirection: "row", alignItems: "center", gap: 3, marginLeft: "auto", maxWidth: 86, flexShrink: 1 }, userTagText: { color: "#e9e6f3", fontSize: 11, minWidth: 0, flexShrink: 1 },
  tabs: { flexDirection: "row", alignItems: "center", justifyContent: "space-around", backgroundColor: "#0d1021", paddingTop: 7, paddingBottom: Platform.OS === "ios" ? 24 : 8, paddingHorizontal: 4, borderTopWidth: 1, borderTopColor: "#55417b" },
  tabItem: { width: "16.66%", minHeight: 53, alignItems: "center", justifyContent: "center", borderRadius: 11, paddingVertical: 3, position: "relative" },
  createTab: { alignSelf: "center" },
  tabIcon: { color: "#a9a4c5", fontSize: 19, lineHeight: 24, textAlign: "center", position: "relative", minWidth: 28, height: 28 },
  activeTabIcon: { color: "#c8a9ff", textShadowColor: "#9a68ff", textShadowRadius: 9 },
  createIcon: { color: "#fff", backgroundColor: "#7548f0", overflow: "hidden", borderRadius: 18, width: 36, height: 36, lineHeight: 35, fontSize: 27, shadowColor: "#875aff", shadowOpacity: 0.65, shadowRadius: 13, shadowOffset: { width: 0, height: 0 }, elevation: 6 },
  tabBadge: { position: "absolute", top: -1, right: -9, minWidth: 15, height: 15, borderRadius: 8, overflow: "hidden", backgroundColor: "#7b4af1", color: "#fff", fontSize: 9, lineHeight: 15, textAlign: "center", fontWeight: "700" },
  tab: { color: "#9e9bb8", fontSize: 10, fontWeight: "600", textAlign: "center" }, activeTab: { color: "#f5f0ff" },
  content: { paddingHorizontal: 18, paddingTop: 23, paddingBottom: 24, flexGrow: 1 }, form: { marginTop: 16 },
  title: { color: "#f4f1ff", fontFamily: "sans-serif", fontSize: 30, fontWeight: "700", letterSpacing: -0.5, marginBottom: 8 },
  eyebrow: { color: "#b79bff", fontSize: 11, letterSpacing: 1.8, textTransform: "uppercase", fontWeight: "700" },
  section: { fontSize: 19, fontFamily: "sans-serif", fontWeight: "700", color: "#eeeaff", marginVertical: 10 },
  copy: { color: "#b2afca", lineHeight: 21, marginVertical: 5 }, handle: { color: "#a5a1c0", fontSize: 13 },
  input: { backgroundColor: "#0d1021", borderWidth: 1, borderColor: "#393653", paddingHorizontal: 13, paddingVertical: 12, borderRadius: 12, marginVertical: 6, color: "#f4f1ff", minHeight: 46 },
  multiline: { minHeight: 82, textAlignVertical: "top" },
  button: { backgroundColor: "#7046e9", borderRadius: 11, paddingVertical: 12, paddingHorizontal: 15, marginVertical: 5, alignItems: "center", alignSelf: "flex-start", minWidth: 116, minHeight: 44, justifyContent: "center", shadowColor: "#7249ed", shadowOpacity: 0.18, shadowRadius: 10, shadowOffset: { width: 0, height: 3 }, elevation: 2 },
  buttonText: { color: "white", fontWeight: "700" }, secondary: { backgroundColor: "#14162c", borderWidth: 1, borderColor: "#3a3554", shadowOpacity: 0 }, secondaryText: { color: "#cdbaff" },
  post: { borderWidth: 1, borderColor: "#302d4d", borderRadius: 17, backgroundColor: "#11142a", padding: 16, marginVertical: 7, shadowColor: "#000", shadowOpacity: 0.22, shadowRadius: 14, shadowOffset: { width: 0, height: 7 }, elevation: 2 }, author: { color: "#f3f0ff", fontWeight: "700" },
  postAuthor: { flexDirection: "row", alignItems: "center", gap: 11, marginBottom: 10 },
  avatarHalo: { alignItems: "center", justifyContent: "center", position: "relative", backgroundColor: "#17152d", borderWidth: 2, borderColor: "#a27cff", shadowColor: "#9868ff", shadowOpacity: 0.48, shadowRadius: 10, shadowOffset: { width: 0, height: 3 }, elevation: 3 },
  avatar: { alignItems: "center", justifyContent: "center", overflow: "hidden", backgroundColor: "#21183d", borderWidth: 2, borderColor: "#101225" },
  avatarPulse: { position: "absolute", top: 2, right: 2, width: 8, height: 8, borderRadius: 4, borderWidth: 1, borderColor: "#e5f8ff", backgroundColor: "#74d7ff", shadowColor: "#68d6ff", shadowOpacity: 0.9, shadowRadius: 7, elevation: 4 },
  avatarImage: { width: "100%", height: "100%" }, avatarInitials: { color: "#e6d9ff", fontWeight: "700", fontSize: 16 },
  profileHero: { flexDirection: "row", alignItems: "center", gap: 17, marginBottom: 12, paddingVertical: 8 },
  unreadNotification: { borderLeftWidth: 3, borderLeftColor: "#9b75ff", paddingLeft: 12, backgroundColor: "#191432" },
  relationshipRow: { borderBottomWidth: 1, borderBottomColor: "#2b2947", paddingVertical: 10 },
  postBody: { color: "#e8e5f7", fontSize: 15, lineHeight: 22, marginVertical: 12 },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: 6 }, row: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 7, marginVertical: 5 },
  link: { color: "#c2a8ff", fontWeight: "700", padding: 8 },
  empty: { alignItems: "center", borderWidth: 1, borderStyle: "solid", borderColor: "#48386d", borderRadius: 18, padding: 24, marginVertical: 20, backgroundColor: "#11142a", shadowColor: "#784ce9", shadowOpacity: 0.14, shadowRadius: 24, shadowOffset: { width: 0, height: 0 }, elevation: 2 },
  error: { padding: 12, backgroundColor: "#321b2c", borderColor: "#70405c", borderWidth: 1, borderRadius: 12, marginBottom: 12 }, errorText: { color: "#ffc4d4" },
  checkLine: { padding: 13, marginVertical: 5, backgroundColor: "#11142a", borderRadius: 12, borderWidth: 1, borderColor: "#393653" },
  messageList: { minHeight: 180, maxHeight: 420, backgroundColor: "#0c0f20", padding: 12, borderRadius: 16, borderWidth: 1, borderColor: "#302d4d", marginVertical: 12 },
  message: { padding: 11, backgroundColor: "#1d1935", borderRadius: 12, marginVertical: 5 },
});

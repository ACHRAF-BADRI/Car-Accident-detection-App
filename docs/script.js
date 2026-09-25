const REPO = "ACHRAF-BADRI/Car-Accident-detection-App";
const RELEASES_PAGE = `https://github.com/${REPO}/releases`;

/* ---------------------------------------------------------------- Translations */
const I18N = {
  en: {
    "nav.features": "Features", "nav.how": "How it works", "nav.screens": "Preview", "nav.download": "Download", "nav.faq": "FAQ",
    "hero.pill": "Windows 10 / 11 · Free and open source",
    "hero.title": 'Detect road accidents <span class="grad">in real time</span>',
    "hero.lead": "AccidentAI analyses a video or a webcam, spots the vehicles and raises an alert as soon as an accident appears — with snapshots, recording and cloud backup.",
    "hero.float": "Snapshot saved and uploaded",
    "cta.download": "Download for Windows", "cta.screens": "See the preview",
    "strip.yolo": "vehicle detection", "strip.cnn": "accident classification", "strip.cloud": "images and videos in the cloud", "strip.lang": "bilingual interface",
    "features.eyebrow": "Features", "features.title": "Everything you need to watch a road",
    "f1.title": "Video or webcam", "f1.text": "Open a video or plug in a camera: analysis runs live, with pause, resume and stop.",
    "f2.title": "Automatic alerts", "f2.text": "Above the threshold you choose, the screen switches to alert and a snapshot of the accident is saved.",
    "f3.title": "Recording", "f3.text": "Record the webcam for hours or days, split into one-hour files, and play it back up to 16×.",
    "f4.title": "Cloud backup", "f4.text": "Every image and video is uploaded automatically, and retried later if the connection drops.",
    "f5.title": "Admin area", "f5.text": "Dashboard, account management (create, suspend, delete) and access to everyone's images and videos.",
    "f6.title": "Modern and bilingual", "f6.text": "Light, dark or system theme, English or French interface, and secure accounts.",
    "how.eyebrow": "How it works", "how.title": "From frame to alert, in three steps",
    "s1.title": "Find the vehicles", "s1.text": "YOLOv3 finds cars, buses, trucks and motorbikes in every frame of the video.",
    "s2.title": "Recognise the accident", "s2.text": "A neural network trained on traffic scenes estimates the probability of an accident.",
    "s3.title": "Alert and keep a record", "s3.text": "Above the threshold: on-screen alert, snapshot saved, cloud upload and an entry in the event log.",
    "screens.eyebrow": "Preview", "screens.title": "A clear interface, built for monitoring",
    "tab.detection": "Detection", "tab.profile": "My profile", "tab.settings": "Settings", "tab.login": "Sign in",
    "cap.detection": "An accident detected live: boxed vehicles, probability and event log.",
    "cap.profile": "My profile: name, email and password, managed by each user.",
    "cap.settings_light": "Settings in the light theme: alert threshold, snapshots, camera, language, recording.",
    "cap.login": "Sign in or create an account, in English or French, light or dark.",
    "dl.title": "Install AccidentAI", "dl.text": "Download the Windows installer, run it, then sign in or create an account.",
    "req.title": "Requirements", "req.os": "Windows 10 or 11, 64-bit", "req.ram": "8 GB of RAM recommended", "req.disk": "About 3 GB of disk space",
    "req.net": "Internet connection for the account and the cloud", "req.cam": "Webcam optional",
    "note.title": "Windows SmartScreen warning",
    "note.text": "The program is not signed: Windows may show “Windows protected your PC”. Click “More info”, then “Run anyway”.",
    "faq.title": "Frequently asked questions",
    "q1": "Is the application free?", "a1": "Yes. The source code is available on GitHub.",
    "q2": "Do I need a graphics card?", "a2": "No, everything runs on the processor. Detection analyses about 2 to 3 frames per second on a recent PC.",
    "q3": "Where are my images and videos stored?", "a3": "On your PC, in a folder of your own account, and a copy is uploaded to the cloud. You can delete them at any time from the application.",
    "q4": "Is detection 100% reliable?", "a4": "No. It is a monitoring aid: it can miss an accident or raise a false alarm. The alert threshold can be tuned in the settings.",
    "q5": "Which videos can I analyse?", "a5": "MP4, AVI, MKV, WEBM and MOV files, and webcams plugged into the PC. Fixed surveillance cameras give the best results.",
    "footer.text": "Accident detection with computer vision — Python, OpenCV, TensorFlow.",
    "release.loading": "Looking for the latest version…",
    "release.found": "Version {version} · {size} · {date}",
    "release.soon": "Installer coming soon — see the releases page on GitHub.",
    "release.soonBtn": "Coming soon on GitHub",
  },
};

// French is the text already written in the HTML: keep it as the reference
const FR = {};
document.querySelectorAll("[data-i18n]").forEach((el) => { FR[el.dataset.i18n] = el.innerHTML; });
Object.assign(FR, {
  "cap.profile": "Mon profil : nom, e-mail et mot de passe, gérés par chaque utilisateur.",
  "cap.settings_light": "Les paramètres en thème clair : seuil d'alerte, captures, caméra, langue, enregistrement.",
  "cap.login": "Connexion ou création de compte, en français ou en anglais, en clair ou en sombre.",
  "release.found": "Version {version} · {size} · {date}",
  "release.soon": "Programme d'installation bientôt disponible — voir la page des versions sur GitHub.",
  "release.soonBtn": "Bientôt disponible sur GitHub",
});
I18N.fr = FR;

let lang = "fr";
let release = null; // { url, version, size, date } or "none"

function t(key) { return (I18N[lang] && I18N[lang][key]) || FR[key] || ""; }

function applyLanguage(next) {
  lang = next;
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const text = t(el.dataset.i18n);
    if (text) el.innerHTML = text; // our own static strings only
  });
  document.getElementById("shot-caption").innerHTML = t(`cap.${currentShot}`);
  showRelease();
  try { localStorage.setItem("lang", lang); } catch (e) { /* storage unavailable: language just isn't remembered */ }
}

/* ---------------------------------------------------------------- Latest release (.exe) */
function formatSize(bytes) {
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`;
}

async function loadRelease() {
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, { headers: { Accept: "application/vnd.github+json" } });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    const asset = (data.assets || []).find((a) => /\.(exe|msi)$/i.test(a.name)) || (data.assets || []).find((a) => /\.zip$/i.test(a.name));
    release = asset
      ? { url: asset.browser_download_url, version: data.tag_name, size: formatSize(asset.size), date: new Date(data.published_at) }
      : "none";
  } catch (e) {
    release = "none"; // no release published yet (404) or GitHub unreachable
  }
  showRelease();
}

function showRelease() {
  const infos = document.querySelectorAll("[data-release-info]");
  const buttons = document.querySelectorAll("[data-download]");
  if (!release) return;
  if (release === "none") {
    infos.forEach((el) => { el.textContent = t("release.soon"); el.classList.add("soon"); });
    buttons.forEach((b) => { b.href = RELEASES_PAGE; b.target = "_blank"; b.rel = "noopener"; b.querySelector("span").textContent = t("release.soonBtn"); });
    return;
  }
  const date = release.date.toLocaleDateString(lang === "fr" ? "fr-FR" : "en-GB", { day: "numeric", month: "long", year: "numeric" });
  infos.forEach((el) => {
    el.classList.remove("soon");
    el.textContent = t("release.found").replace("{version}", release.version).replace("{size}", release.size).replace("{date}", date);
  });
  buttons.forEach((b) => { b.href = release.url; b.removeAttribute("target"); b.querySelector("span").textContent = t("cta.download"); });
}

/* ---------------------------------------------------------------- Screenshots */
let currentShot = "detection";
const shotImg = document.getElementById("shot-img");

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === tab));
    currentShot = tab.dataset.shot;
    shotImg.classList.add("fading");
    setTimeout(() => {
      shotImg.src = `assets/screens/${currentShot}.jpg`;
      shotImg.onload = () => shotImg.classList.remove("fading");
    }, 180);
    document.getElementById("shot-caption").innerHTML = t(`cap.${currentShot}`);
  });
});

const lightbox = document.getElementById("lightbox");
const lightboxImg = document.getElementById("lightbox-img");
function openLightbox(src) { lightboxImg.src = src; lightbox.hidden = false; document.body.style.overflow = "hidden"; }
function closeLightbox() { lightbox.hidden = true; document.body.style.overflow = ""; }
document.getElementById("shot").addEventListener("click", () => openLightbox(shotImg.src));
document.querySelector(".hero .window img").addEventListener("click", (e) => openLightbox(e.target.src));
lightbox.addEventListener("click", (e) => { if (e.target !== lightboxImg) closeLightbox(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !lightbox.hidden) closeLightbox(); });

/* ---------------------------------------------------------------- Mobile menu */
const menu = document.getElementById("menu-toggle");
const links = document.getElementById("nav-links");
menu.addEventListener("click", () => {
  const open = links.classList.toggle("open");
  menu.setAttribute("aria-expanded", open);
});
links.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => links.classList.remove("open")));

/* ---------------------------------------------------------------- Reveal on scroll */
const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (entry.isIntersecting) { entry.target.classList.add("visible"); observer.unobserve(entry.target); }
  });
}, { threshold: 0.12 });
document.querySelectorAll(".reveal").forEach((el) => observer.observe(el));

/* ---------------------------------------------------------------- Start */
document.getElementById("lang-toggle").addEventListener("click", () => applyLanguage(lang === "fr" ? "en" : "fr"));
let saved = null;
try { saved = localStorage.getItem("lang"); } catch (e) { /* ignore */ }
const browserLang = (navigator.language || "fr").toLowerCase().startsWith("fr") ? "fr" : "en";
applyLanguage(saved === "fr" || saved === "en" ? saved : browserLang);
loadRelease();

// Service worker do chat: recebe os pushes e mostra as notificações.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// Pushes são processados um de cada vez, para agrupar certo mensagens que chegam juntas.
let fila = Promise.resolve();

self.addEventListener("push", (event) => {
  let dados = {};
  try { dados = event.data ? event.data.json() : {}; } catch (e) {}
  const tarefa = fila.then(() => mostrar(dados));
  fila = tarefa.catch(() => {});
  event.waitUntil(tarefa);
});

async function mostrar(dados) {
  const titulo = dados.titulo || "Nova mensagem";
  const chave = dados.chave || "MURAL";
  // Várias mensagens da mesma conversa viram uma notificação só (últimas 5 linhas).
  const anteriores = await self.registration.getNotifications({ tag: chave });
  const linhas = anteriores.length ? (anteriores[0].data?.linhas || []) : [];
  linhas.push(dados.corpo || "");
  const extra = linhas.length > 1 ? " (" + linhas.length + ")" : "";
  await self.registration.showNotification(titulo + extra, {
    body: linhas.slice(-5).join("\n"),
    tag: chave,
    renotify: true,
    icon: "/icones/icone-192.png",
    badge: "/icones/badge-96.png",
    vibrate: [200, 100, 200],
    data: { chave, linhas: linhas.slice(-50) },
  });
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const chave = event.notification.data?.chave || "MURAL";
  event.waitUntil((async () => {
    const janelas = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const janela of janelas) {
      if (new URL(janela.url).origin === self.location.origin) {
        await janela.focus();
        janela.postMessage({ tipo: "abrir", chave });
        return;
      }
    }
    await self.clients.openWindow("/?c=" + encodeURIComponent(chave));
  })());
});

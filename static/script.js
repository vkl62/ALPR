// -----------------------
// Вкладки
// -----------------------
function showTab(id, event) {
    document.querySelectorAll('.tab-content').forEach(t => t.style.display = 'none');
    document.getElementById(id).style.display = 'block';

    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    if (event && event.currentTarget) {
        event.currentTarget.classList.add('active');
    }
}

// -----------------------
// Статусбар
// -----------------------
async function refreshStatus() {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();

        document.getElementById("statusTime").innerText = new Date().toLocaleTimeString();

        const indicator = document.getElementById("statusIndicator");
        if (data.mqtt === "OK" && data.cpai === "OK") {
            indicator.style.background = "#0a0";
        } else {
            indicator.style.background = "#c00";
        }

        if (document.getElementById("statusModal").style.display === "block") {
            document.getElementById("modalMQTT").innerText = data.mqtt;
            document.getElementById("modalCPAI").innerText = data.cpai;
        }
    } catch (err) {
        document.getElementById("modalMQTT").innerText = "Нет соединения";
        document.getElementById("modalCPAI").innerText = "Нет соединения";
        document.getElementById("statusTime").innerText = new Date().toLocaleTimeString();
        document.getElementById("statusIndicator").style.background = "#c00";
    }
}

setInterval(refreshStatus, 2000);
refreshStatus();

// -----------------------
// Лог
// -----------------------
let logAutoScroll = true;

async function refreshLog() {
    try {
        const res = await fetch("/api/log");
        const data = await res.json();

        const out = document.getElementById("logOutput");
        if (!out) return;

        const showDebug = document.getElementById("chkDebug")?.checked;

        out.innerHTML = "";
        (data.log || []).forEach(line => {
            if (!showDebug && line.includes("[DEBUG]")) return; // фильтр debug
            const p = document.createElement("div");
            p.textContent = line;
            out.appendChild(p);
        });

        if (logAutoScroll) out.scrollTop = out.scrollHeight;
    } catch (err) {
        console.error("Ошибка загрузки лога:", err);
    }
}

setInterval(refreshLog, 2000);

document.getElementById("chkAutoScroll")?.addEventListener("change", function () {
    logAutoScroll = this.checked;
});

// Загружаем начальное состояние чекбокса при загрузке страницы
fetch("/api/settings")
    .then(res => res.json())
    .then(settings => {
        document.getElementById("chkDebug").checked = settings.debug || false;
    })
    .catch(console.error);

// Существующий обработчик изменений (оставляем как есть)
document.getElementById("chkDebug")?.addEventListener("change", function () {
    const checked = this.checked;
    fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ debug: checked })
    }).then(() => refreshLog());
});


// -----------------------
// Люди
// -----------------------
async function loadPeople(search = "") {
    try {
        const res = await fetch("/api/people");
        const data = await res.json();

        const tbody = document.querySelector("#peopleTable tbody");
        if (!tbody) return;

        tbody.innerHTML = "";
        (data.people || [])
            .filter(p => {
                const s = search.toLowerCase();
                return (
                    !s ||
                    p.name.toLowerCase().includes(s) ||
                    (p.car_number || "").toLowerCase().includes(s) ||
                    (p.car_model || "").toLowerCase().includes(s) ||
                    (p.phone || "").toLowerCase().includes(s) ||
                    (p.address || "").toLowerCase().includes(s)
                );
            })
            .forEach(p => {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td contenteditable="true" data-field="name" data-id="${p.id}">${p.name}</td>
                    <td contenteditable="true" data-field="car_number" data-id="${p.id}">${p.car_number}</td>
                    <td contenteditable="true" data-field="car_model" data-id="${p.id}">${p.car_model}</td>
                    <td contenteditable="true" data-field="phone" data-id="${p.id}">${p.phone}</td>
                    <td contenteditable="true" data-field="address" data-id="${p.id}">${p.address || ""}</td>
                    <td>
                        <button onclick="deletePerson(${p.id})">Удалить</button>
                        <button onclick="savePerson(${p.id})">Сохранить</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
    } catch (err) {
        console.error("Ошибка загрузки людей:", err);
    }
}

document.getElementById("searchPeople")?.addEventListener("input", e => loadPeople(e.target.value));

async function addPerson() {
    const fields = ["name", "car_number", "car_model", "phone", "address"];
    const payload = {};
    fields.forEach(f => { payload[f] = document.getElementById(f).value; });

    try {
        await fetch("/api/people", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        fields.forEach(f => { document.getElementById(f).value = ""; });
        loadPeople();
    } catch (err) {
        console.error("Ошибка добавления человека:", err);
    }
}

async function deletePerson(id) {
    await fetch("/api/people/" + id, { method: "DELETE" });
    loadPeople();
}

async function savePerson(id) {
    const tds = document.querySelectorAll(`[data-id='${id}']`);
    const payload = {};
    tds.forEach(td => { payload[td.dataset.field] = td.innerText; });
    payload.id = id;

    await fetch("/api/people", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
    loadPeople();
}

// -----------------------
// Точки доступа
// -----------------------
function safeNameForFile(name) {
    return name ? name.replace(/[^A-Za-z0-9_\-]/g, "_") : name;
}

async function loadPoints(search = "") {
    try {
        const res = await fetch("/api/points");
        const data = await res.json();

        const tbody = document.querySelector("#pointsTable tbody");
        if (!tbody) return;

        tbody.innerHTML = "";
        (data.points || [])
            .filter(p => {
                const s = search.toLowerCase();
                const mqtt_branch = `${getBaseTopic()}/${p.name}`;
                return (
                    !s ||
                    p.name.toLowerCase().includes(s) ||
                    (p.mqtt_topic || "").toLowerCase().includes(s) ||
                    (p.in_camera_url || "").toLowerCase().includes(s) ||
                    (p.out_camera_url || "").toLowerCase().includes(s) ||
                    mqtt_branch.toLowerCase().includes(s)
                );
            })
            .forEach(p => {
                const safe = safeNameForFile(p.name);
                const mqtt_branch_in = `${getBaseTopic()}/${p.name}/IN`;
                const mqtt_branch_out = `${getBaseTopic()}/${p.name}/OUT`;

                const thumbIn = p.in_camera_url ? `/static/snapshots/${safe}_in.jpg?${Date.now()}` : "";
                const thumbOut = p.out_camera_url ? `/static/snapshots/${safe}_out.jpg?${Date.now()}` : "";
                const thumbsHTML = `
                    <div style="display:flex;gap:6px;align-items:center;">
                        ${p.in_camera_url ? `<div>IN<br><img class="snapshot" src="${thumbIn}" onclick="openImage('${thumbIn}')"></div>` : ""}
                        ${p.out_camera_url ? `<div>OUT<br><img class="snapshot" src="${thumbOut}" onclick="openImage('${thumbOut}')"></div>` : ""}
                    </div>
                `;

                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td contenteditable="true" data-field="name" data-id="${p.id}">${p.name}</td>
                    <td contenteditable="true" data-field="mqtt_topic" data-id="${p.id}">${p.mqtt_topic}</td>
                    <td contenteditable="true" data-field="in_camera_url" data-id="${p.id}">${p.in_camera_url || ""}</td>
                    <td contenteditable="true" data-field="out_camera_url" data-id="${p.id}">${p.out_camera_url || ""}</td>
                    <td>${thumbsHTML}</td>
                    <td>
                        <button onclick="deletePoint(${p.id})">Удалить</button>
                        <button onclick="savePoint(${p.id})">Сохранить</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
    } catch (err) {
        console.error("Ошибка загрузки точек:", err);
    }
}

document.getElementById("searchPoints")?.addEventListener("input", e => loadPoints(e.target.value));

async function addPoint() {
    const name = document.getElementById("point_name").value;
    const in_url = document.getElementById("point_rtp_in").value;
    const out_url = document.getElementById("point_rtp_out").value;

    try {
        await fetch("/api/points", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, in_camera_url: in_url, out_camera_url: out_url })
        });

        document.getElementById("point_name").value = "";
        document.getElementById("point_rtp_in").value = "";
        document.getElementById("point_rtp_out").value = "";

        loadPoints();
    } catch (err) {
        console.error("Ошибка добавления точки:", err);
    }
}

async function deletePoint(id) {
    await fetch("/api/points/" + id, { method: "DELETE" });
    loadPoints();
}

async function savePoint(id) {
    const tds = document.querySelectorAll(`[data-id='${id}']`);
    const payload = {};
    tds.forEach(td => { payload[td.dataset.field] = td.innerText; });
    payload.id = id;

    await fetch("/api/points", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
    loadPoints();
}

// -----------------------
// Миниатюры
// -----------------------
function openImage(url) {
    window.open(url, "_blank");
}

// -----------------------
// Настройки
// -----------------------
function getBaseTopic() {
    const baseTopicInput = document.getElementById("mqttBase");
    return baseTopicInput ? baseTopicInput.value.trim() || "ALPR" : "ALPR";
}
// Функция загрузки настроек
async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        const s = await res.json();

        // Обновляем поля ввода для CPAI
        document.getElementById("cpaiHost").value = s.cpai.host || "192.168.12.11";
        document.getElementById("cpaiPort").value = s.cpai.port || 32168;

        // Обновляем остальные поля
        document.getElementById("mqttHost").value = s.mqtt.host || "";
        document.getElementById("mqttPort").value = s.mqtt.port || 1883;
        document.getElementById("mqttBase").value = s.mqtt.base_topic || "ALPR";
        document.getElementById("baseDb").value = s.paths.base_db || "base.db";
        document.getElementById("snapshotsPath").value = s.paths.snapshots || "static/snapshots";
    } catch (err) {
        console.error("Ошибка загрузки настроек:", err);
    }
}

//  Функция сохранения настроек
async function saveSettings() {
    const mqttHost = document.getElementById("mqttHost").value;
    const mqttPort = Number(document.getElementById("mqttPort").value) || 1883;
    const mqttBase = document.getElementById("mqttBase").value || "ALPR";
    
    const cpaiHost = document.getElementById("cpaiHost").value;
    const cpaiPort = Number(document.getElementById("cpaiPort").value) || 32168;
    
    const baseDb = document.getElementById("baseDb").value || "base.db";
    const snapshots = document.getElementById("snapshotsPath").value || "static/snapshots";

    const payload = {
        mqtt: { host: mqttHost, port: mqttPort, base_topic: mqttBase },
        cpai: { host: cpaiHost, port: cpaiPort },
        paths: { base_db: baseDb, snapshots: snapshots }
    };

    await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    });
    alert("Настройки сохранены");
}


// Обработчик кнопки перезапуска сервера
async function restartService() {
    try {
        const response = await fetch("/api/restart", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ service: "alpr" }) // имя службы по умолчанию
        });
        
        const data = await response.json();
        if (data.status === "restarting") {
            alert("Служба перезапускается...");
        } else {
            alert("Ошибка при перезапуске: " + data.error);
        }
    } catch (err) {
        console.error("Ошибка перезапуска:", err);
        alert("Не удалось перезапустить службу");
    }
}


// -----------------------
// Статус-модал
// -----------------------
function toggleStatus() {
    const modal = document.getElementById("statusModal");
    const statusBtn = document.getElementById("btnStatus");

    if (modal.style.display === "block") {
        if (document.activeElement && modal.contains(document.activeElement)) {
            statusBtn.focus();
        }
        modal.style.display = "none";
    } else {
        modal.style.display = "block";
        loadStatusModal();
        modal.querySelector("button")?.focus();
    }
}

async function loadStatusModal() {
    try {
        const sres = await fetch("/api/status");
        const s = await sres.json();

        document.getElementById("modalMQTT").innerText = s.mqtt;
        document.getElementById("modalCPAI").innerText = s.cpai;
    } catch (e) {
        console.warn(e);
    }
}
// -----------------------
// История событий
// -----------------------
const histState = {
    search: "",
    from: "",
    to: "",
    limit: 50,
    offset: 0,
    total: 0
};

async function loadHistory() {
    const params = new URLSearchParams();
    if (histState.search) params.set("search", histState.search);
    if (histState.from) params.set("from", histState.from);
    if (histState.to) params.set("to", histState.to);
    params.set("limit", String(histState.limit));
    params.set("offset", String(histState.offset));

    try {
        const res = await fetch("/api/history?" + params.toString());
        const data = await res.json();

        const tbody = document.querySelector("#historyTable tbody");
        if (!tbody) return;
        tbody.innerHTML = "";

        (data.items || []).forEach(row => {
            const tr = document.createElement("tr");
            // row.timestamp, row.plate, row.point_name
            tr.innerHTML = `
                <td>${row.timestamp || ""}</td>
                <td>${row.plate || ""}</td>
                <td>${row.point_name || ""}</td>
            `;
            tbody.appendChild(tr);
        });

        // Пагинация
        histState.total = data.total || 0;
        const fromIdx = Math.min(histState.offset + 1, histState.total);
        const toIdx = Math.min(histState.offset + (data.items?.length || 0), histState.total);

        document.getElementById("histInfo").innerText =
            histState.total ? `Показаны ${fromIdx}–${toIdx} из ${histState.total}` : "Ничего не найдено";

        document.getElementById("histPrev").disabled = histState.offset <= 0;
        document.getElementById("histNext").disabled = (histState.offset + histState.limit) >= histState.total;
    } catch (err) {
        console.error("Ошибка загрузки истории:", err);
    }
}

function applyHistoryFilters() {
    const q = document.getElementById("histSearch")?.value?.trim() || "";
    const from = document.getElementById("histFrom")?.value || "";
    const to = document.getElementById("histTo")?.value || "";

    histState.search = q;
    histState.from = from;
    histState.to = to;
    histState.offset = 0;
    loadHistory();
}

function resetHistoryFilters() {
    document.getElementById("histSearch").value = "";
    document.getElementById("histFrom").value = "";
    document.getElementById("histTo").value = "";

    histState.search = "";
    histState.from = "";
    histState.to = "";
    histState.offset = 0;
    loadHistory();
}

// Навигация страниц
document.getElementById("histPrev")?.addEventListener("click", () => {
    histState.offset = Math.max(0, histState.offset - histState.limit);
    loadHistory();
});
document.getElementById("histNext")?.addEventListener("click", () => {
    histState.offset = histState.offset + histState.limit;
    loadHistory();
});

// Поиск по Enter
document.getElementById("histSearch")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") applyHistoryFilters();
});

// -----------------------
// Инициализация
// -----------------------
document.addEventListener("DOMContentLoaded", () => {
    loadPeople();
    loadPoints();
    refreshLog();
    refreshStatus();
    loadSettings();
    loadHistory();
});

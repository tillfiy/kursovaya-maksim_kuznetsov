// Нагрузочный тест сервиса заявок (ДЗ 2), префикс maksim_kuznetsov.
//
// Открытая модель нагрузки: k6 запускает запросы с заданной частотой независимо
// от того, успел ли сервис ответить на предыдущие (executor constant-arrival-rate).
//
// Параметры запуска (-e ИМЯ=значение):
//   SCENARIO  mixed — смешанный профиль по весам; heavy — только самая тяжёлая операция
//   RATE      частота, запросов в секунду (по умолчанию 2)
//   DURATION  длительность ступени (по умолчанию 30s)
//   BASE_URL  адрес сервиса (по умолчанию http://localhost:8080)
//   OUT       файл для итогов ступени в JSON (по умолчанию results/load/<SCENARIO>_<RATE>.json)
//
// Пример: k6 run -e SCENARIO=mixed -e RATE=4 -e DURATION=30s load/test.js

import http from 'k6/http';
import { check } from 'k6';

const SCENARIO = __ENV.SCENARIO || 'mixed';
const RATE = Number(__ENV.RATE || 2);
const DURATION = __ENV.DURATION || '30s';
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';
const OUT = __ENV.OUT || `results/load/${SCENARIO}_${RATE}.json`;
const TICKETS = 100000; // заявок в рабочем наполнении

// Отказы по правилам варианта — не ошибки: 409 возвращается при недопустимом
// переходе статуса и при комментарии к закрытой заявке.
http.setResponseCallback(http.expectedStatuses(200, 201, 409));

// Профиль нагрузки: доля операции в общем потоке, сумма весов — 100.
// Обоснование весов — в отчёте (таблица профиля нагрузки).
const PROFILE = [
  { op: 'ticket_card', weight: 30 },
  { op: 'tickets_list', weight: 25 },
  { op: 'tickets_filter', weight: 15 },
  { op: 'add_comment', weight: 10 },
  { op: 'create_ticket', weight: 6 },
  { op: 'tickets_search', weight: 5 },
  { op: 'change_status', weight: 5 },
  { op: 'categories', weight: 2 },
  { op: 'me', weight: 1 },
  { op: 'summary', weight: 1 },
];
const HEAVY = 'tickets_search';

const OPS = [...new Set([...PROFILE.map((p) => p.op), HEAVY])];

// Порог (одинаков для всех ступеней): p95 < 500 мс и доля ошибок < 1 %.
// Метрики считаются только по запросам нагрузки (тег phase:load), вход в них не попадает.
// Пороги вида max>=0 ничего не ограничивают — они нужны, чтобы k6 посчитал
// метрики отдельно по каждой операции для разбора ошибок и времени.
const thresholds = {
  'http_req_duration{phase:load}': ['p(95)<500'],
  'http_req_failed{phase:load}': ['rate<0.01'],
  'http_reqs{phase:load}': ['count>=0'],
};
for (const op of OPS) {
  thresholds[`http_req_duration{op:${op}}`] = ['max>=0'];
  thresholds[`http_req_failed{op:${op}}`] = ['rate>=0'];
}

export const options = {
  scenarios: {
    [SCENARIO]: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: Math.max(10, RATE * 2),
      maxVUs: Math.max(50, RATE * 20),
      gracefulStop: '30s',
      tags: { phase: 'load' },
      exec: SCENARIO === 'heavy' ? 'heavy' : 'mixed',
    },
  },
  thresholds,
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)'],
};

// Вход один раз до нагрузки: токен передаётся всем виртуальным пользователям.
export function setup() {
  const r = http.post(`${BASE_URL}/api/auth/login`,
    JSON.stringify({ login: 'demo', password: 'demo' }),
    { headers: { 'Content-Type': 'application/json' }, tags: { phase: 'setup' } });
  if (r.status !== 200) throw new Error(`Вход не удался: ${r.status} ${r.body}`);
  return { token: r.json('token') };
}

const rnd = (n) => 1 + Math.floor(Math.random() * n);

function request(op, token) {
  const params = {
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    tags: { op },
  };
  const json = (o) => JSON.stringify(o);
  switch (op) {
    case 'me':
      return http.get(`${BASE_URL}/api/me`, params);
    case 'categories':
      return http.get(`${BASE_URL}/api/categories`, params);
    case 'tickets_list':
      return http.get(`${BASE_URL}/api/tickets?page=${rnd(3)}&size=20`, params);
    case 'tickets_filter': {
      const status = ['new', 'in_progress'][rnd(2) - 1];
      return http.get(`${BASE_URL}/api/tickets?status=${status}&category_id=${rnd(10)}&page=1&size=20`, params);
    }
    case 'tickets_search':
      return http.get(`${BASE_URL}/api/tickets?q=${encodeURIComponent('принтер')}&page=1&size=20`, params);
    case 'ticket_card':
      return http.get(`${BASE_URL}/api/tickets/${rnd(TICKETS)}`, params);
    case 'summary':
      return http.get(`${BASE_URL}/api/summary`, params);
    case 'create_ticket':
      return http.post(`${BASE_URL}/api/tickets`,
        json({ title: 'k6: заявка', body: 'создана нагрузочным тестом', category_id: rnd(10) }), params);
    case 'add_comment':
      return http.post(`${BASE_URL}/api/tickets/${rnd(TICKETS)}/comments`,
        json({ body: 'k6: комментарий' }), params);
    case 'change_status': {
      const status = ['in_progress', 'closed'][rnd(2) - 1];
      return http.patch(`${BASE_URL}/api/tickets/${rnd(TICKETS)}/status`, json({ status }), params);
    }
    default:
      throw new Error(`неизвестная операция ${op}`);
  }
}

function pickOp() {
  let x = Math.random() * 100;
  for (const p of PROFILE) {
    if ((x -= p.weight) < 0) return p.op;
  }
  return PROFILE[PROFILE.length - 1].op;
}

function run(op, token) {
  const r = request(op, token);
  check(r, { 'ответ по контракту': (res) => [200, 201, 409].includes(res.status) });
}

export function mixed(data) {
  run(pickOp(), data.token);
}

export function heavy(data) {
  run(HEAVY, data.token);
}

// Итог ступени: строка в консоль и JSON-файл со всеми метриками.
export function handleSummary(data) {
  const m = data.metrics;
  const d = m['http_req_duration{phase:load}'] ? m['http_req_duration{phase:load}'].values : {};
  const failed = m['http_req_failed{phase:load}'] ? m['http_req_failed{phase:load}'].values.rate : 0;
  const count = m['http_reqs{phase:load}'] ? m['http_reqs{phase:load}'].values.count : 0;
  const dropped = m.dropped_iterations ? m.dropped_iterations.values.count : 0;
  const seconds = parseInt(DURATION, 10) * (DURATION.endsWith('m') ? 60 : 1);
  const ok = d['p(95)'] < 500 && failed < 0.01;
  const f = (x) => (x === undefined ? '—' : x.toFixed(1));
  let text = `\n[maksim_kuznetsov] ${SCENARIO}, ${RATE} запр/с, ${DURATION}: ` +
    `p50=${f(d.med)} мс, p95=${f(d['p(95)'])} мс, max=${f(d.max)} мс, ` +
    `ошибок ${(failed * 100).toFixed(2)} %, dropped=${dropped}, ` +
    `факт. частота ${(count / seconds).toFixed(2)} запр/с — порог ${ok ? 'ВЫДЕРЖАН' : 'НАРУШЕН'}\n`;
  for (const op of OPS) {
    const od = m[`http_req_duration{op:${op}}`];
    if (!od || !od.values.max) continue;
    const of = m[`http_req_failed{op:${op}}`];
    text += `    ${op.padEnd(16)} p50=${f(od.values.med).padStart(8)}  p95=${f(od.values['p(95)']).padStart(8)}` +
      `  ошибок ${((of ? of.values.rate : 0) * 100).toFixed(1)} %\n`;
  }
  return { stdout: text, [OUT]: JSON.stringify({ scenario: SCENARIO, rate: RATE, duration: DURATION, metrics: m }, null, 1) };
}

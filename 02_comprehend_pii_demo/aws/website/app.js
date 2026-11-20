/**
 * Amazon Comprehend demo - website logic (no build step, no external libraries).
 *
 * Pages: 1 PII detection, 2 Mask PII, 3 Spot possible bias (sentiment by group, toxicity).
 * Every Comprehend call goes through this demo's API (config.js sets COMPREHEND_API_URL).
 * All user-supplied text is inserted with textContent (never innerHTML), so pasted
 * text cannot inject markup.
 */
(function () {
    'use strict';

    const API_BASE = (window.COMPREHEND_API_URL || '').replace(/\/+$/, '');
    const FALLBACK_LIMITS = { maxTextChars: 10000, maxItemBytes: 1000, sentimentBatch: 25, toxicityBatch: 10 };
    const MAX_UPLOAD_ROWS = 300;
    const PAGES = ['pii', 'mask', 'bias'];

    const state = {
        info: null,
        limits: FALLBACK_LIMITS,
        mask: { text: '', entities: [], seq: 0, timer: null },
        bias: { rows: [], dataset: null, results: null },
        tox: { results: null },
    };

    // ------------------------------------------------------------------ helpers

    const el = (id) => document.getElementById(id);

    function clear(node) {
        while (node.firstChild) node.removeChild(node.firstChild);
    }

    /** Tiny DOM builder. Strings become text nodes, so nothing is ever parsed as HTML. */
    function h(tag, attrs, ...kids) {
        const node = document.createElement(tag);
        for (const [key, value] of Object.entries(attrs || {})) {
            if (value === false || value == null) continue;
            if (key === 'class') node.className = value;
            else if (key === 'text') node.textContent = value;
            else node.setAttribute(key, value === true ? '' : value);
        }
        for (const kid of kids.flat(Infinity)) {
            if (kid === false || kid == null) continue;
            node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
        }
        return node;
    }

    function debounce(fn, ms) {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => fn(...args), ms);
        };
    }

    function byteLength(text) {
        return new TextEncoder().encode(text).length;
    }

    function typeColor(type) {
        let hash = 0;
        for (const ch of type) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
        return `hsl(${hash}, 75%, 82%)`;
    }

    function showBanner(message) {
        const banner = el('banner');
        banner.textContent = message;
        banner.hidden = false;
    }

    function clearBanner() {
        el('banner').hidden = true;
    }

    function setStatus(id, message) {
        el(id).textContent = message || '';
    }

    function renderTable(table, columns, rows) {
        clear(table);
        table.append(h('thead', {}, h('tr', {}, columns.map((c) => h('th', { text: c.label })))));
        table.append(
            h('tbody', {}, rows.map((row) =>
                h('tr', {}, columns.map((c) => h('td', { class: c.num ? 'num' : '' }, c.cell(row))))
            ))
        );
    }

    function meter(value, max) {
        const fill = h('span');
        fill.style.left = '0';
        fill.style.width = `${Math.max(0, Math.min(1, value / max)) * 100}%`;
        return h('div', { class: 'meter' }, fill);
    }

    // ---------------------------------------------------------------- API calls

    async function callApi(path, body) {
        let response;
        try {
            response = await fetch(API_BASE + path, body === undefined ? {} : {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
        } catch (err) {
            throw new Error('Could not reach the API. Check your connection, or that your IP address is allowed.');
        }
        let data = null;
        try { data = await response.json(); } catch (err) { /* non-JSON error body */ }
        if (!response.ok) {
            if (response.status === 429) throw new Error('Too many requests right now. Please wait a moment and try again.');
            if (response.status === 403) throw new Error('The API refused this request. Your IP address may not be on the allow-list.');
            throw new Error((data && (data.error || data.message)) || `The API returned HTTP ${response.status}.`);
        }
        return data;
    }

    async function fetchText(url) {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`Could not load ${url} (HTTP ${response.status}).`);
        return response.text();
    }

    // ------------------------------------------------------- pure data functions

    /** Small RFC 4180 CSV parser: quoted fields, escaped quotes, CRLF or LF. */
    function parseCSV(input) {
        const text = input.replace(/^\uFEFF/, '');
        const rows = [];
        let row = [];
        let field = '';
        let inQuotes = false;
        for (let i = 0; i < text.length; i++) {
            const c = text[i];
            if (inQuotes) {
                if (c === '"') {
                    if (text[i + 1] === '"') { field += '"'; i++; } else { inQuotes = false; }
                } else {
                    field += c;
                }
            } else if (c === '"') {
                inQuotes = true;
            } else if (c === ',') {
                row.push(field); field = '';
            } else if (c === '\n' || c === '\r') {
                if (c === '\r' && text[i + 1] === '\n') i++;
                row.push(field); rows.push(row); row = []; field = '';
            } else {
                field += c;
            }
        }
        if (field !== '' || row.length) { row.push(field); rows.push(row); }
        return rows.filter((r) => r.some((cell) => cell.trim() !== ''));
    }

    /** sample_data/pii_mask_samples.txt: '### title' line, samples separated by '---'. */
    function parsePiiSamples(raw) {
        const samples = [];
        raw.replace(/\r\n/g, '\n').split('\n---\n').forEach((block) => {
            const trimmed = block.trim();
            if (!trimmed) return;
            const newline = trimmed.indexOf('\n');
            const title = (newline === -1 ? trimmed : trimmed.slice(0, newline)).replace(/^[#\s]+/, '').trim();
            const body = newline === -1 ? '' : trimmed.slice(newline + 1).trim();
            samples.push({ title, body });
        });
        return samples;
    }

    /** rows: [{group, sentiment, net}] -> one summary per group, sorted by group name. */
    function summariseGroups(rows) {
        const groups = new Map();
        rows.forEach((r) => {
            if (!groups.has(r.group)) groups.set(r.group, []);
            groups.get(r.group).push(r);
        });
        return [...groups.entries()]
            .sort((a, b) => a[0].localeCompare(b[0]))
            .map(([group, items]) => {
                const share = (label) => (items.filter((r) => r.sentiment === label).length / items.length) * 100;
                return {
                    group,
                    n: items.length,
                    avgNet: items.reduce((sum, r) => sum + r.net, 0) / items.length,
                    pctNegative: share('NEGATIVE'),
                    pctMixed: share('MIXED'),
                    pctPositive: share('POSITIVE'),
                };
            });
    }

    function sentimentVerdict(summary, threshold) {
        if (summary.length < 2) {
            return { kind: 'info', message: 'Only one group in this data, so there is nothing to compare.' };
        }
        const sorted = [...summary].sort((a, b) => a.avgNet - b.avgNet);
        const lowest = sorted[0];
        const highest = sorted[sorted.length - 1];
        const gap = highest.avgNet - lowest.avgNet;
        if (gap >= threshold) {
            return {
                kind: 'warn',
                message: `Possible bias signal. Text about ${lowest.group} averages ${gap.toFixed(2)} lower net sentiment ` +
                    `than text about ${highest.group} (flag threshold ${threshold.toFixed(2)}). ` +
                    'Check that the texts describe comparable situations, then look at the wording below.',
            };
        }
        return {
            kind: 'ok',
            message: `No large sentiment gap between groups (gap ${gap.toFixed(2)}, flag threshold ${threshold.toFixed(2)}).`,
        };
    }

    /** Text with PII wrapped in <mark>. Offsets are character (code point) offsets, like Comprehend's. */
    function buildHighlight(text, entities) {
        const chars = Array.from(text);
        const fragment = document.createDocumentFragment();
        let pos = 0;
        [...entities].sort((a, b) => a.BeginOffset - b.BeginOffset).forEach((e) => {
            if (e.BeginOffset < pos) return; // overlapping span
            if (e.BeginOffset > pos) fragment.append(chars.slice(pos, e.BeginOffset).join(''));
            const mark = h('mark', { class: 'pii', title: `${e.Type} (${e.Score.toFixed(2)})` },
                chars.slice(e.BeginOffset, e.EndOffset).join(''));
            mark.style.background = typeColor(e.Type);
            fragment.append(mark);
            pos = e.EndOffset;
        });
        if (pos < chars.length) fragment.append(chars.slice(pos).join(''));
        return fragment;
    }

    // ------------------------------------------------------------ navigation / info

    function showPage() {
        const wanted = location.hash.replace('#', '');
        const page = PAGES.includes(wanted) ? wanted : 'pii';
        PAGES.forEach((name) => {
            el(`page-${name}`).hidden = name !== page;
            document.querySelector(`[data-nav="${name}"]`).classList.toggle('active', name === page);
        });
    }

    function initSubtabs() {
        document.querySelectorAll('.subtab').forEach((button) => {
            button.addEventListener('click', () => {
                document.querySelectorAll('.subtab').forEach((b) => b.classList.toggle('active', b === button));
                ['sentiment', 'toxicity'].forEach((name) => {
                    el(`bias-panel-${name}`).hidden = name !== button.dataset.subtab;
                });
            });
        });
    }

    function renderCodePanels() {
        document.querySelectorAll('.code-target').forEach((target) => {
            clear(target);
            target.dataset.fns.split(',').forEach((name) => {
                const source = state.info && state.info.functions[name];
                if (source) target.append(h('pre', { class: 'code' }, h('code', { text: source })));
            });
            if (!target.firstChild) target.append(h('p', { class: 'hint', text: 'Code not available (could not reach the API).' }));
        });
    }

    async function loadInfo() {
        try {
            state.info = await callApi('/info');
            state.limits = Object.assign({}, FALLBACK_LIMITS, state.info.limits);
        } catch (err) {
            showBanner(err.message);
        }
        el('pii-text').maxLength = state.limits.maxTextChars;
        el('mask-text').maxLength = state.limits.maxTextChars;
        renderCodePanels();
    }

    // ------------------------------------------------------------- page 1: PII

    function renderPii(text, data) {
        el('pii-results').hidden = false;
        const found = data.entities.length > 0;
        el('pii-empty').hidden = found;
        el('pii-found').hidden = !found;
        if (!found) return;

        const highlight = el('pii-highlight');
        clear(highlight);
        highlight.append(buildHighlight(text, data.entities));

        renderTable(el('pii-table'), [
            { label: 'Type', cell: (e) => h('code', { text: e.Type }) },
            { label: 'Text', cell: (e) => e.Text },
            { label: 'Score', num: true, cell: (e) => e.Score.toFixed(3) },
            { label: 'Offset', num: true, cell: (e) => `${e.BeginOffset}\u2013${e.EndOffset}` },
        ], data.entities);

        el('pii-raw').textContent = JSON.stringify(data.raw, null, 2);
    }

    function initPii() {
        let seq = 0;
        let timer = null;

        async function run() {
            const text = el('pii-text').value;
            if (!text.trim()) {
                seq++;
                el('pii-results').hidden = true;
                setStatus('pii-status', '');
                return;
            }
            const mine = ++seq;
            setStatus('pii-status', 'Calling Amazon Comprehend\u2026');
            try {
                const data = await callApi('/pii', { text });
                if (mine !== seq) return;
                clearBanner();
                renderPii(text, data);
                setStatus('pii-status', '');
            } catch (err) {
                if (mine !== seq) return;
                setStatus('pii-status', '');
                showBanner(err.message);
            }
        }

        el('pii-text').addEventListener('input', () => {
            clearTimeout(timer);
            if (el('pii-auto').checked) timer = setTimeout(run, 700);
        });
        el('pii-run').addEventListener('click', () => { clearTimeout(timer); run(); });
        return run;
    }

    // ------------------------------------------------------------ page 2: masking

    function maskOptions() {
        const style = document.querySelector('input[name="mask-style"]:checked').value;
        const types = [...document.querySelectorAll('#mask-types input:checked')].map((box) => box.dataset.type);
        return {
            style,
            mask_char: el('mask-char').value || '*',
            min_score: parseFloat(el('mask-min').value),
            types,
        };
    }

    async function requestMask() {
        const m = state.mask;
        if (!m.entities.length) return;
        const mine = ++m.seq;
        const options = maskOptions();
        try {
            const data = await callApi('/mask', {
                text: m.text,
                entities: m.entities.map((e) => ({
                    Type: e.Type, Score: e.Score, BeginOffset: e.BeginOffset, EndOffset: e.EndOffset,
                })),
                ...options,
            });
            if (mine !== m.seq) return;
            clearBanner();
            el('mask-original').textContent = m.text;
            el('mask-masked').textContent = data.masked;
            el('mask-masked-title').textContent = `Masked (${data.count} of ${m.entities.length} entities)`;
            renderTable(el('mask-table'), [
                { label: 'Type', cell: (e) => h('code', { text: e.Type }) },
                { label: 'Text', cell: (e) => e.Text },
                { label: 'Score', num: true, cell: (e) => e.Score.toFixed(3) },
                {
                    label: 'Masked',
                    cell: (e) => (e.Score >= options.min_score && options.types.includes(e.Type) ? 'Yes' : 'No'),
                },
            ], m.entities);
        } catch (err) {
            if (mine === m.seq) showBanner(err.message);
        }
    }

    function initMask() {
        const scheduleMask = debounce(requestMask, 200);

        el('mask-run').addEventListener('click', async () => {
            const text = el('mask-text').value;
            if (!text.trim()) return;
            el('mask-run').disabled = true;
            setStatus('mask-status', 'Calling Amazon Comprehend\u2026');
            try {
                const data = await callApi('/pii', { text });
                clearBanner();
                state.mask.text = text;
                state.mask.entities = data.entities;
                el('mask-results').hidden = false;
                const found = data.entities.length > 0;
                el('mask-empty').hidden = found;
                el('mask-found').hidden = !found;
                if (found) {
                    const types = [...new Set(data.entities.map((e) => e.Type))].sort();
                    const box = el('mask-types');
                    clear(box);
                    types.forEach((type) => {
                        const input = h('input', { type: 'checkbox', checked: true, 'data-type': type });
                        input.addEventListener('change', scheduleMask);
                        box.append(h('label', { class: 'inline' }, input, type));
                    });
                    await requestMask();
                }
            } catch (err) {
                showBanner(err.message);
            } finally {
                el('mask-run').disabled = false;
                setStatus('mask-status', '');
            }
        });

        document.querySelectorAll('input[name="mask-style"]').forEach((radio) => {
            radio.addEventListener('change', () => {
                el('mask-char').disabled = maskOptions().style !== 'mask';
                scheduleMask();
            });
        });
        el('mask-char').addEventListener('input', scheduleMask);
        el('mask-min').addEventListener('input', () => {
            el('mask-min-val').textContent = parseFloat(el('mask-min').value).toFixed(2);
            scheduleMask();
        });
        el('mask-sample').addEventListener('change', () => {
            const index = el('mask-sample').selectedIndex;
            el('mask-text').value = index === 0 ? '' : state.maskSamples[index - 1].body;
        });
    }

    async function loadMaskSamples() {
        try {
            state.maskSamples = parsePiiSamples(await fetchText('sample_data/pii_mask_samples.txt'));
            const select = el('mask-sample');
            clear(select);
            select.append(h('option', { text: '(write your own)' }));
            state.maskSamples.forEach((s) => select.append(h('option', { text: s.title })));
        } catch (err) {
            showBanner(err.message);
        }
    }

    // ------------------------------------------------- page 3: sentiment by group

    function datasetKey(kind, label, count) {
        return `${kind}|${label}|${count}`;
    }

    function setDataset(dataset) {
        state.bias.dataset = dataset;
        const wrap = el('bias-preview-wrap');
        wrap.hidden = !dataset;
        el('bias-run').disabled = !dataset;
        if (dataset) {
            renderTable(el('bias-preview'), [
                { label: 'Group', cell: (r) => r.group },
                { label: 'Text', cell: (r) => r.text },
            ], dataset.rows);
        }
        renderSentiment();
    }

    function useSampleScenario() {
        const scenario = el('bias-scenario').value;
        const rows = state.bias.rows.filter((r) => r.scenario === scenario);
        setDataset(rows.length ? { key: datasetKey('sample', scenario, rows.length), rows } : null);
    }

    function readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error('Could not read that file.'));
            reader.readAsText(file);
        });
    }

    async function useUploadedFile() {
        const file = el('bias-file').files[0];
        const message = el('bias-upload-msg');
        if (!file) { setDataset(null); message.textContent = ''; return; }
        try {
            const table = parseCSV(await readFile(file));
            const header = (table[0] || []).map((c) => c.trim().toLowerCase());
            const g = header.indexOf('group');
            const t = header.indexOf('text');
            if (g < 0 || t < 0) {
                setDataset(null);
                message.textContent = 'The CSV needs `group` and `text` columns.';
                return;
            }
            let rows = table.slice(1)
                .map((r) => ({ group: (r[g] || '').trim(), text: (r[t] || '').trim() }))
                .filter((r) => r.group && r.text);
            message.textContent = `${rows.length} rows loaded.`;
            if (rows.length > MAX_UPLOAD_ROWS) {
                rows = rows.slice(0, MAX_UPLOAD_ROWS);
                message.textContent = `Using the first ${MAX_UPLOAD_ROWS} rows to keep the demo quick.`;
            }
            setDataset(rows.length ? { key: datasetKey('upload', file.name, rows.length), rows } : null);
        } catch (err) {
            setDataset(null);
            message.textContent = err.message;
        }
    }

    async function runSentiment() {
        const dataset = state.bias.dataset;
        if (!dataset) return;
        const tooLong = dataset.rows.filter((r) => byteLength(r.text) > state.limits.maxItemBytes).length;
        if (tooLong) {
            showBanner(`${tooLong} text(s) are longer than ${state.limits.maxItemBytes.toLocaleString()} bytes. Shorten them and try again.`);
            return;
        }
        el('bias-run').disabled = true;
        const scored = [];
        const batch = state.limits.sentimentBatch;
        try {
            for (let i = 0; i < dataset.rows.length; i += batch) {
                const chunk = dataset.rows.slice(i, i + batch);
                setStatus('bias-status', `Calling Amazon Comprehend\u2026 ${i} of ${dataset.rows.length}`);
                const data = await callApi('/sentiment', { texts: chunk.map((r) => r.text) });
                data.results.forEach((res, j) => scored.push({
                    group: chunk[j].group, text: chunk[j].text, sentiment: res.sentiment, net: res.net,
                }));
            }
            clearBanner();
            state.bias.results = { key: dataset.key, scored };
            renderSentiment();
        } catch (err) {
            showBanner(err.message);
        } finally {
            el('bias-run').disabled = !state.bias.dataset;
            setStatus('bias-status', '');
        }
    }

    function renderSentiment() {
        const { dataset, results } = state.bias;
        const visible = Boolean(dataset && results && results.key === dataset.key);
        el('bias-results').hidden = !visible;
        if (!visible) return;

        const threshold = parseFloat(el('bias-threshold').value);
        el('bias-threshold-val').textContent = threshold.toFixed(2);
        const summary = summariseGroups(results.scored);

        renderTable(el('bias-summary'), [
            { label: 'Group', cell: (s) => s.group },
            { label: 'Texts', num: true, cell: (s) => s.n },
            { label: 'Avg net sentiment', num: true, cell: (s) => s.avgNet.toFixed(3) },
            { label: '% negative', num: true, cell: (s) => Math.round(s.pctNegative) },
            { label: '% mixed', num: true, cell: (s) => Math.round(s.pctMixed) },
            { label: '% positive', num: true, cell: (s) => Math.round(s.pctPositive) },
        ], summary);

        const bars = el('bias-bars');
        clear(bars);
        summary.forEach((s) => {
            const fill = h('div', { class: `bar-fill ${s.avgNet >= 0 ? 'pos' : 'neg'}` });
            fill.style.width = `${Math.min(1, Math.abs(s.avgNet)) * 50}%`;
            if (s.avgNet >= 0) fill.style.left = '50%'; else fill.style.right = '50%';
            bars.append(h('div', { class: 'bar-row' },
                h('span', { text: s.group }),
                h('div', { class: 'bar-track' }, fill),
                h('span', { class: 'bar-value', text: s.avgNet.toFixed(2) })));
        });

        const verdict = sentimentVerdict(summary, threshold);
        const verdictEl = el('bias-verdict');
        verdictEl.className = `verdict ${verdict.kind}`;
        verdictEl.textContent = verdict.message;

        const rows = [...results.scored].sort((a, b) => a.group.localeCompare(b.group) || a.net - b.net);
        renderTable(el('bias-rows'), [
            { label: 'Group', cell: (r) => r.group },
            { label: 'Text', cell: (r) => r.text },
            { label: 'Sentiment', cell: (r) => r.sentiment },
            { label: 'Net sentiment', num: true, cell: (r) => r.net.toFixed(3) },
        ], rows);
    }

    function initBias() {
        el('bias-run').addEventListener('click', runSentiment);
        el('bias-threshold').addEventListener('input', renderSentiment);
        el('bias-scenario').addEventListener('change', useSampleScenario);
        el('bias-file').addEventListener('change', useUploadedFile);
        document.querySelectorAll('input[name="bias-source"]').forEach((radio) => {
            radio.addEventListener('change', () => {
                const upload = document.querySelector('input[name="bias-source"]:checked').value === 'upload';
                el('bias-sample-wrap').hidden = upload;
                el('bias-upload-wrap').hidden = !upload;
                if (upload) useUploadedFile(); else useSampleScenario();
            });
        });
    }

    async function loadBiasDataset() {
        try {
            const table = parseCSV(await fetchText('sample_data/bias_dataset.csv'));
            const header = table[0].map((c) => c.trim().toLowerCase());
            const [s, g, t] = ['scenario', 'group', 'text'].map((name) => header.indexOf(name));
            state.bias.rows = table.slice(1).map((r) => ({ scenario: r[s], group: r[g], text: r[t] }));
            const scenarios = [...new Set(state.bias.rows.map((r) => r.scenario))];
            const select = el('bias-scenario');
            clear(select);
            scenarios.forEach((name) => select.append(h('option', { value: name, text: name })));
            useSampleScenario();
        } catch (err) {
            showBanner(err.message);
        }
    }

    // ------------------------------------------------------------ page 3: toxicity

    function renderToxicity() {
        const saved = state.tox.results;
        el('tox-results').hidden = !saved;
        const threshold = parseFloat(el('tox-threshold').value);
        el('tox-threshold-val').textContent = threshold.toFixed(2);
        if (!saved) return;

        const labelNames = [...new Set(saved.results.flatMap((r) => Object.keys(r.labels)))].sort();
        const rows = saved.lines.map((line, i) => ({ line, ...saved.results[i] }));
        const flagged = (r) => Object.entries(r.labels)
            .filter(([, score]) => score >= threshold)
            .sort((a, b) => b[1] - a[1])
            .map(([name]) => name)
            .join(', ') || '-';

        renderTable(el('tox-table'), [
            { label: 'Text', cell: (r) => r.line },
            {
                label: 'Toxicity',
                cell: (r) => h('div', { class: 'bar-cell' }, r.toxicity.toFixed(2), meter(r.toxicity, 1)),
            },
            { label: 'Flagged as', cell: flagged },
            ...labelNames.map((name) => ({
                label: name, num: true, cell: (r) => (r.labels[name] !== undefined ? r.labels[name].toFixed(2) : '-'),
            })),
        ], rows);
    }

    function initToxicity() {
        el('tox-threshold').addEventListener('input', renderToxicity);
        el('tox-run').addEventListener('click', async () => {
            const lines = el('tox-text').value.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
            if (!lines.length) return;
            const tooLong = lines.filter((l) => byteLength(l) > state.limits.maxItemBytes).length;
            if (tooLong) {
                showBanner(`${tooLong} line(s) are longer than ${state.limits.maxItemBytes.toLocaleString()} bytes. Shorten them and try again.`);
                return;
            }
            el('tox-run').disabled = true;
            const results = [];
            const batch = state.limits.toxicityBatch;
            try {
                for (let i = 0; i < lines.length; i += batch) {
                    setStatus('tox-status', `Calling Amazon Comprehend\u2026 ${i} of ${lines.length}`);
                    const data = await callApi('/toxicity', { texts: lines.slice(i, i + batch) });
                    results.push(...data.results);
                }
                clearBanner();
                state.tox.results = { lines, results };
                renderToxicity();
            } catch (err) {
                showBanner(err.message);
            } finally {
                el('tox-run').disabled = false;
                setStatus('tox-status', '');
            }
        });
    }

    async function loadToxicitySamples() {
        try {
            el('tox-text').value = (await fetchText('sample_data/toxicity_samples.txt')).trim();
        } catch (err) {
            showBanner(err.message);
        }
    }

    // --------------------------------------------------------------------- start

    async function init() {
        window.addEventListener('hashchange', showPage);
        showPage();
        initSubtabs();
        const runPii = initPii();
        initMask();
        initBias();
        initToxicity();
        await Promise.all([loadInfo(), loadMaskSamples(), loadBiasDataset(), loadToxicitySamples()]);
        return { runPii };
    }

    window.ComprehendDemo = {
        parseCSV, parsePiiSamples, summariseGroups, sentimentVerdict, buildHighlight, init, state,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else if (!window.__COMPREHEND_NO_AUTOSTART) {
        init();
    }
})();

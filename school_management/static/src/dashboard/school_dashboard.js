import { Component, markRaw, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { SchoolChart } from "./school_chart";

// Reference data-viz palette: categorical slots in fixed order, plus chart chrome.
// Dark steps are selected for the dark surface, not an automatic flip.
const THEMES = {
    light: {
        series: ["#2a78d6", "#eb6834", "#1baf7a"],
        surface: "#ffffff",
        ink: "#0b0b0b",
        muted: "#898781",
        grid: "#e1e0d9",
        axis: "#c3c2b7",
        areaAlpha: "1a",
    },
    dark: {
        series: ["#3987e5", "#d95926", "#199e70"],
        surface: "#1a1a19",
        ink: "#f0efec",
        muted: "#898781",
        grid: "#2c2c2a",
        axis: "#383835",
        areaAlpha: "26",
    },
};
const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

function detectTheme() {
    const bg = getComputedStyle(document.body).backgroundColor.match(/\d+/g) || [255, 255, 255];
    const [r, g, b] = bg.map(Number);
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.5 ? THEMES.dark : THEMES.light;
}

export class SchoolDashboard extends Component {
    static template = "school_management.Dashboard";
    static components = { SchoolChart };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.theme = detectTheme();
        this.isDark = this.theme === THEMES.dark;
        this.state = useState({ data: null, termId: false, loading: true });
        this.charts = markRaw({});
        onWillStart(() => this.load());
    }

    async load(termId = this.state.termId) {
        this.state.loading = true;
        const data = await this.orm.call("school.dashboard", "get_dashboard_data", [], {
            term_id: termId || false,
        });
        this.charts = markRaw(this.buildCharts(data));
        this.state.data = markRaw(data);
        this.state.termId = data.term ? data.term.id : false;
        this.state.loading = false;
    }

    onTermChange(ev) {
        this.load(parseInt(ev.target.value) || false);
    }

    // ------------------------------------------------------------------
    // Formatting
    // ------------------------------------------------------------------
    num(value) {
        return new Intl.NumberFormat(undefined).format(value || 0);
    }

    compact(value) {
        return new Intl.NumberFormat(undefined, {
            notation: "compact",
            maximumFractionDigits: 1,
        }).format(value || 0);
    }

    money(value, compact = true) {
        const { symbol, position, digits } = this.state.data.currency;
        const amount = compact
            ? this.compact(value)
            : new Intl.NumberFormat(undefined, {
                  minimumFractionDigits: digits,
                  maximumFractionDigits: digits,
              }).format(value || 0);
        return position === "before" ? `${symbol} ${amount}` : `${amount} ${symbol}`;
    }

    pct(value) {
        return value === null || value === undefined ? "–" : `${value}%`;
    }

    meter(used, total) {
        const ratio = total ? Math.min(used / total, 1) : 0;
        let level = "good";
        if (ratio >= 0.95) {
            level = "critical";
        } else if (ratio >= 0.8) {
            level = "warning";
        }
        return { width: `${Math.round(ratio * 100)}%`, pct: Math.round(ratio * 100), level };
    }

    // ------------------------------------------------------------------
    // Charts
    // ------------------------------------------------------------------
    baseOptions({ stacked = false, yMax, yFormat, legend = false, onClick } = {}) {
        const t = this.theme;
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 300 },
            interaction: { mode: "index", intersect: false },
            onClick,
            onHover: (event, elements) => {
                if (onClick) {
                    event.native.target.style.cursor = elements.length ? "pointer" : "default";
                }
            },
            plugins: {
                legend: {
                    display: legend,
                    position: "top",
                    align: "start",
                    labels: {
                        color: t.ink,
                        font: { family: FONT, size: 12 },
                        usePointStyle: true,
                        pointStyle: "rectRounded",
                        boxWidth: 10,
                        boxHeight: 10,
                        padding: 16,
                    },
                },
                tooltip: {
                    backgroundColor: t.ink,
                    titleColor: t.surface,
                    bodyColor: t.surface,
                    titleFont: { family: FONT, weight: "600" },
                    bodyFont: { family: FONT },
                    padding: 10,
                    cornerRadius: 6,
                    boxPadding: 4,
                    usePointStyle: true,
                    callbacks: yFormat
                        ? { label: (ctx) => ` ${ctx.dataset.label}: ${yFormat(ctx.parsed.y)}` }
                        : {},
                },
            },
            scales: {
                x: {
                    stacked,
                    grid: { display: false },
                    border: { color: t.axis },
                    ticks: { color: t.muted, font: { family: FONT, size: 11 }, maxRotation: 0, autoSkip: true },
                },
                y: {
                    stacked,
                    beginAtZero: true,
                    max: yMax,
                    grid: { color: t.grid, lineWidth: 1 },
                    border: { display: false },
                    ticks: {
                        color: t.muted,
                        font: { family: FONT, size: 11 },
                        maxTicksLimit: 6,
                        callback: (v) => (yFormat ? yFormat(v) : this.compact(v)),
                    },
                },
            },
        };
    }

    barDataset(label, data, color, { top = true, stacked = false } = {}) {
        return {
            label,
            data,
            backgroundColor: color,
            hoverBackgroundColor: color,
            maxBarThickness: 24,
            // 4px rounded data-end, square at the baseline; 2px surface gap between stacked segments.
            borderRadius: top ? { topLeft: 4, topRight: 4 } : 0,
            borderSkipped: "start",
            borderColor: this.theme.surface,
            borderWidth: stacked ? { top: 2 } : 0,
        };
    }

    buildCharts(data) {
        const t = this.theme;
        const charts = {};

        const level = data.enrolment_by_level;
        if (level && level.labels.length) {
            const datasets = [
                this.barDataset(_t("Boys"), level.male, t.series[0], { top: false, stacked: true }),
                this.barDataset(_t("Girls"), level.female, t.series[1], { stacked: true }),
            ];
            if (level.other.some((v) => v)) {
                datasets[1].borderRadius = 0;
                datasets.push(this.barDataset(_t("Not set"), level.other, t.series[2], { stacked: true }));
            }
            charts.enrolment = {
                type: "bar",
                data: { labels: level.labels, datasets },
                options: this.baseOptions({
                    stacked: true,
                    legend: true,
                    yFormat: (v) => this.num(v),
                    onClick: (ev, els) =>
                        els.length && this.openStudents([["level_id", "=", level.level_ids[els[0].index]]], level.labels[els[0].index]),
                }),
            };
        }

        const trend = data.attendance_trend;
        if (trend && trend.labels.length) {
            charts.attendance = {
                type: "line",
                data: {
                    labels: trend.labels,
                    datasets: [
                        {
                            label: _t("Attendance"),
                            data: trend.rates,
                            borderColor: t.series[0],
                            backgroundColor: t.series[0] + t.areaAlpha,
                            fill: "origin",
                            borderWidth: 2,
                            borderCapStyle: "round",
                            borderJoinStyle: "round",
                            tension: 0,
                            pointRadius: 4,
                            pointHoverRadius: 6,
                            pointHitRadius: 12,
                            pointBackgroundColor: t.series[0],
                            pointBorderColor: t.surface,
                            pointBorderWidth: 2,
                        },
                    ],
                },
                options: this.baseOptions({ yMax: 100, yFormat: (v) => `${v}%` }),
            };
        }

        const scores = data.scores_by_class;
        if (scores && scores.labels.length) {
            charts.scores = {
                type: "bar",
                data: {
                    labels: scores.labels,
                    datasets: [this.barDataset(_t("Mean score"), scores.means, t.series[0])],
                },
                options: this.baseOptions({
                    yMax: 100,
                    yFormat: (v) => `${v}%`,
                    onClick: (ev, els) =>
                        els.length && this.openReportCards(scores.class_ids[els[0].index], scores.labels[els[0].index]),
                }),
            };
        }

        const fees = data.fees_by_class;
        if (fees && fees.labels.length) {
            charts.fees = {
                type: "bar",
                data: {
                    labels: fees.labels,
                    datasets: [
                        this.barDataset(_t("Collected"), fees.collected, t.series[0], { top: false, stacked: true }),
                        this.barDataset(_t("Outstanding"), fees.outstanding, t.series[1], { stacked: true }),
                    ],
                },
                options: this.baseOptions({
                    stacked: true,
                    legend: true,
                    yFormat: (v) => this.money(v),
                    onClick: (ev, els) => els.length && this.openTermInvoices(fees.class_ids[els[0].index]),
                }),
            };
        }
        return charts;
    }

    // ------------------------------------------------------------------
    // Drill-down
    // ------------------------------------------------------------------
    openWindow(name, resModel, domain, { views, context } = {}) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: resModel,
            domain,
            context: context || {},
            views: views || [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    openStudents(domain = [], name = _t("Students")) {
        this.openWindow(name, "school.student", [["state", "=", "enrolled"], ...domain], {
            views: [
                [false, "list"],
                [false, "kanban"],
                [false, "form"],
            ],
        });
    }

    openStudent(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "school.student",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    openAdmissions(states) {
        this.openWindow(_t("Admission Applications"), "school.admission", [["state", "in", states]]);
    }

    openRegister(classId, className) {
        this.openWindow(_t("Attendance – %s", className), "school.attendance", [["class_id", "=", classId]], {
            context: { default_class_id: classId },
        });
    }

    openExamResults(examId, name) {
        this.openWindow(name, "school.exam.result", [["exam_id", "=", examId]], {
            views: [[false, "list"]],
            context: { default_exam_id: examId, search_default_unmarked: 1 },
        });
    }

    openReportCards(classId, className) {
        const domain = [["class_id", "=", classId]];
        if (this.state.termId) {
            domain.push(["term_id", "=", this.state.termId]);
        }
        this.openWindow(_t("Report Cards – %s", className), "school.report.card", domain);
    }

    openTermInvoices(classId) {
        const domain = [
            ["move_type", "=", "out_invoice"],
            ["student_id", "!=", false],
        ];
        if (this.state.termId) {
            domain.push(["school_term_id", "=", this.state.termId]);
        }
        if (classId) {
            domain.push(["student_id.class_id", "=", classId]);
        }
        this.openWindow(_t("Student Invoices"), "account.move", domain, {
            context: { default_move_type: "out_invoice" },
        });
    }

    openOutstanding() {
        this.openWindow(_t("Unpaid Student Invoices"), "account.move", [
            ["move_type", "=", "out_invoice"],
            ["student_id", "!=", false],
            ["state", "=", "posted"],
            ["payment_state", "in", ["not_paid", "partial"]],
        ]);
    }

    openLoans(states) {
        this.openWindow(_t("Library Loans"), "school.library.loan", [["state", "in", states]]);
    }

    openAction(xmlId) {
        this.actionService.doAction(xmlId);
    }
}

registry.category("actions").add("school_management.dashboard", SchoolDashboard);

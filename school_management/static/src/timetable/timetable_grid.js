import { Component, markRaw, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const SUBJECT_TONES = 10;

export class TimetableGrid extends Component {
    static template = "school_management.TimetableGrid";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({ data: null, mode: "class", resId: false, yearId: false, loading: true });
        this.cells = {};
        this.todayKey = String((new Date().getDay() + 6) % 7); // Monday = "0"
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const data = await this.orm.call("school.timetable.entry", "get_timetable_grid", [], {
            mode: this.state.mode,
            res_id: this.state.resId || false,
            year_id: this.state.yearId || false,
        });
        const cells = {};
        for (const entry of data.entries) {
            cells[`${entry.weekday}-${entry.period_id}`] = entry;
        }
        this.cells = markRaw(cells);
        this.state.data = markRaw(data);
        this.state.resId = data.current ? data.current.id : false;
        this.state.yearId = data.year ? data.year.id : false;
        this.state.loading = false;
    }

    // ------------------------------------------------------------------
    // Filters
    // ------------------------------------------------------------------
    setMode(mode) {
        if (mode !== this.state.mode) {
            this.state.mode = mode;
            this.state.resId = false;
            this.load();
        }
    }

    onSelectRecord(ev) {
        this.state.resId = parseInt(ev.target.value) || false;
        this.load();
    }

    onSelectYear(ev) {
        this.state.yearId = parseInt(ev.target.value) || false;
        this.state.resId = false;
        this.load();
    }

    get options() {
        const data = this.state.data;
        return this.state.mode === "teacher" ? data.teachers : data.classes;
    }

    // ------------------------------------------------------------------
    // Display helpers
    // ------------------------------------------------------------------
    cell(weekday, periodId) {
        return this.cells[`${weekday}-${periodId}`];
    }

    time(value) {
        const hours = Math.floor(value);
        const minutes = Math.round((value - hours) * 60);
        return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
    }

    tone(subjectId) {
        return `o_tt_tone_${subjectId % SUBJECT_TONES}`;
    }

    get lessonCount() {
        return this.state.data.entries.length;
    }

    // ------------------------------------------------------------------
    // Actions
    // ------------------------------------------------------------------
    openEntry(entryId) {
        this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("Lesson"),
                res_model: "school.timetable.entry",
                res_id: entryId,
                views: [[false, "form"]],
                target: "new",
            },
            { onClose: () => this.load() }
        );
    }

    newEntry(weekday, periodId) {
        const data = this.state.data;
        if (!data.can_edit || !data.current) {
            return;
        }
        const context = { default_weekday: weekday, default_period_id: periodId };
        if (this.state.mode === "teacher") {
            context.default_teacher_id = data.current.id;
        } else {
            context.default_class_id = data.current.id;
        }
        this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("New Lesson"),
                res_model: "school.timetable.entry",
                views: [[false, "form"]],
                target: "new",
                context,
            },
            { onClose: () => this.load() }
        );
    }

    printGrid() {
        const data = this.state.data;
        if (!data || !data.current) {
            return;
        }
        // The report reads the class or teacher from `data` (see report.school_management.report_timetable).
        this.actionService.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: "school_management.report_timetable",
            report_file: "school_management.report_timetable",
            name: _t("Timetable"),
            data: { mode: this.state.mode, res_id: data.current.id, year_id: this.state.yearId || false },
        });
    }

    openList() {
        this.actionService.doAction("school_management.action_school_timetable");
    }

    openPeriods() {
        this.actionService.doAction("school_management.action_school_period");
    }
}

registry.category("actions").add("school_management.timetable_grid", TimetableGrid);

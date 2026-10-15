import { Component, onWillStart, onWillUnmount, useEffect, useRef } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";

/**
 * Thin OWL wrapper around Chart.js (bundled with Odoo as web.chartjs_lib).
 * The chart is rebuilt whenever the `config` prop object changes.
 */
export class SchoolChart extends Component {
    static template = "school_management.SchoolChart";
    static props = {
        config: Object,
        height: { type: Number, optional: true },
        ariaLabel: { type: String, optional: true },
    };
    static defaultProps = { height: 260 };

    setup() {
        this.canvasRef = useRef("canvas");
        this.chart = null;
        onWillStart(() => loadBundle("web.chartjs_lib"));
        useEffect(
            (config) => {
                this.chart?.destroy();
                this.chart = new Chart(this.canvasRef.el, config);
            },
            () => [this.props.config]
        );
        onWillUnmount(() => this.chart?.destroy());
    }
}

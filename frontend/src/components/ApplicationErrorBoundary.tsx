import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw, TriangleAlert } from "lucide-react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export default class ApplicationErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Uncaught React render error", error, info.componentStack);
  }

  private retry = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    if (!this.state.error) return this.props.children;

    return (
      <main className="min-h-screen bg-bg flex items-center justify-center px-6 text-text-primary">
        <section
          className="w-full max-w-lg rounded-2xl border border-border bg-panel p-8 shadow-xl"
          role="alert"
        >
          <TriangleAlert className="mb-4 text-amber-400" size={32} aria-hidden="true" />
          <h1 className="mb-2 text-xl font-bold">STL Studio hit an unexpected error</h1>
          <p className="mb-6 text-sm leading-relaxed text-text-secondary-alt">
            Your saved catalog data is unchanged. Try the screen again; if the error returns,
            reload STL Studio and copy the diagnostics from Help → About &amp; support.
          </p>
          <div className="flex flex-wrap gap-3">
            <button className="btn-cta inline-flex items-center gap-2 px-4 py-2" onClick={this.retry}>
              <RefreshCw size={15} aria-hidden="true" /> Try again
            </button>
            <button
              className="rounded border border-border px-4 py-2 text-sm hover:bg-panel-secondary"
              onClick={() => window.location.reload()}
            >
              Reload STL Studio
            </button>
          </div>
        </section>
      </main>
    );
  }
}

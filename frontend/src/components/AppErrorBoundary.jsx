import { Component } from 'react'
import { logError } from '../lib/runtimeLogger'

function trimComponentStack(stack) {
  if (!stack) return null
  return stack
    .trim()
    .split('\n')
    .slice(0, 12)
    .join('\n')
}

export class AppErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
    this.handleReset = this.handleReset.bind(this)
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    logError(`react.boundary.${this.props.scope ?? 'app'}`, error?.message ?? 'React render failed', {
      name: error?.name,
      stack: error?.stack,
      componentStack: trimComponentStack(info?.componentStack),
    })
  }

  handleReset() {
    this.setState({ error: null })
    this.props.onReset?.()
  }

  render() {
    if (!this.state.error) return this.props.children

    if (typeof this.props.fallback === 'function') {
      return this.props.fallback({
        error: this.state.error,
        reset: this.handleReset,
      })
    }

    return (
      <div className="boundary-shell">
        <div className="boundary-card">
          <p className="eyebrow">Runtime Error</p>
          <h2>{this.props.title ?? '界面渲染失败'}</h2>
          <p className="boundary-copy">
            {this.props.description ?? '当前界面发生了运行时异常。错误已写入日志，可直接重试渲染。'}
          </p>
          <p className="boundary-error">{this.state.error?.message ?? 'Unknown error'}</p>
          <div className="boundary-actions">
            <button type="button" className="toolbar-button is-active" onClick={this.handleReset}>
              重新尝试
            </button>
          </div>
        </div>
      </div>
    )
  }
}

/**
 * GenAI Model Selection Demo - Frontend Application
 * Educational demonstration of provider-agnostic GenAI architecture
 * 
 * This application showcases:
 * - Provider-agnostic API interactions
 * - Real-time metrics and monitoring
 * - Session history and analytics
 * - Educational transparency in system behavior
 */

class GenAIDemo {
    constructor() {
        // Configuration
        this.config = {
            apiBaseUrl: 'https://YOUR-API-ID.execute-api.us-east-1.amazonaws.com/Prod',
            sessionId: this.generateSessionId(),
            maxRetries: 3,
            retryDelay: 1000
        };

        // State management
        this.state = {
            isLoading: false,
            sessionMetrics: {
                totalQueries: 0,
                totalTokens: 0,
                averageLatency: 0,
                providerDistribution: {
                    anthropic: 0,
                    openai: 0,
                    nova: 0
                }
            },
            queryHistory: [],
            providerStatus: {
                anthropic: { status: 'unknown', latency: 0, successRate: 0 },
                openai: { status: 'unknown', latency: 0, successRate: 0 },
                nova: { status: 'unknown', latency: 0, successRate: 0 }
            },
            failureSimulations: {
                anthropic: false,
                openai: false,
                nova: false
            },
            // Jev router comparison feature
            routerMode: 'custom',           // custom | jev | compare
            executeRouter: 'none',          // none | custom | jev (compare mode only)
            jev: {
                configured: false,          // set from GET /health -> jev.configured
                mode: 'live',               // "live" | "recorded"
                healthChecked: false,       // whether the initial health check has resolved
                confidenceThreshold: 0.3    // UI slider value; synced from /health on load
            },
            // The query behind the most recent comparison response, kept so the
            // "Run with Custom"/"Run with Jev" actions can resend it with an
            // execute_router selection without re-asking for the text.
            lastComparisonQuery: null
        };

        // Initialize the application
        this.init();
    }

    /**
     * Initialize the application
     */
    init() {
        console.log('GenAI Model Selection Demo - Initializing...');
        
        this.bindEventListeners();
        this.initializeUI();
        this.initializeEducationalFeatures();
        this.checkProviderHealth();
        
        // Set up periodic health checks
        setInterval(() => this.checkProviderHealth(), 30000); // Every 30 seconds
        
        console.log('GenAI Model Selection Demo - Ready');
        this.showToast('🎓 Educational demo ready! Hover over ℹ️ icons for learning tips', 'info', 6000);
    }

    /**
     * Generate a unique session ID
     */
    generateSessionId() {
        return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    /**
     * Bind event listeners to UI elements
     */
    bindEventListeners() {
        // Query submission
        const submitBtn = document.getElementById('submitQuery');
        const queryInput = document.getElementById('queryInput');
        
        submitBtn.addEventListener('click', () => this.submitQuery());
        queryInput.addEventListener('input', () => this.validateInput());
        queryInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && e.ctrlKey) {
                this.submitQuery();
            }
        });

        // History management
        const clearHistoryBtn = document.getElementById('clearHistory');
        clearHistoryBtn.addEventListener('click', () => this.clearHistory());

        // Admin panel toggle
        const adminToggle = document.getElementById('toggleAdminPanel');
        adminToggle.addEventListener('click', () => this.toggleAdminPanel());

        // Failure simulation controls
        const anthropicToggle = document.getElementById('simulateAnthropicFailure');
        const openaiToggle = document.getElementById('simulateOpenAIFailure');
        const novaToggle = document.getElementById('simulateNovaFailure');
        const resetSimBtn = document.getElementById('resetSimulations');

        anthropicToggle.addEventListener('change', (e) => this.toggleProviderSimulation('anthropic', e.target.checked));
        openaiToggle.addEventListener('change', (e) => this.toggleProviderSimulation('openai', e.target.checked));
        novaToggle.addEventListener('change', (e) => this.toggleProviderSimulation('nova', e.target.checked));
        resetSimBtn.addEventListener('click', () => this.resetSimulations());

        // Router mode selection (Jev comparison feature)
        const routerModeRadios = document.querySelectorAll('input[name="routerMode"]');
        routerModeRadios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.setRouterMode(e.target.value);
                }
            });
        });

        // Execute-with selection (compare mode only)
        const executeRouterRadios = document.querySelectorAll('input[name="executeRouter"]');
        executeRouterRadios.forEach(radio => {
            radio.addEventListener('change', (e) => {
                if (e.target.checked) {
                    this.state.executeRouter = e.target.value;
                }
            });
        });

        // Run-with actions shown after a routing-only comparison. These resend
        // the stored query in Compare mode with the chosen execute_router, so a
        // single model runs without re-asking for the query text.
        const runWithCustomBtn = document.getElementById('runWithCustomBtn');
        const runWithJevBtn = document.getElementById('runWithJevBtn');
        if (runWithCustomBtn) {
            runWithCustomBtn.addEventListener('click', () => this.runComparisonWith('custom'));
        }
        if (runWithJevBtn) {
            runWithJevBtn.addEventListener('click', () => this.runComparisonWith('jev'));
        }

        // Jev confidence threshold slider (Jev comparison feature).
        const thresholdSlider = document.getElementById('jevThresholdSlider');
        if (thresholdSlider) {
            thresholdSlider.addEventListener('input', (e) => this.setConfidenceThreshold(e.target.value));
        }
    }

    /**
     * Record the UI confidence-threshold value and update its readout. The
     * value is sent with the next query as `confidence_threshold`, overriding
     * the server default for that request.
     *
     * @param {number|string} value The slider value in [0, 1].
     */
    setConfidenceThreshold(value) {
        let num = Number(value);
        if (!Number.isFinite(num)) num = 0.3;
        num = Math.max(0, Math.min(1, num));
        this.state.jev.confidenceThreshold = num;
        const readout = document.getElementById('jevThresholdValue');
        if (readout) readout.textContent = num.toFixed(2);
        const slider = document.getElementById('jevThresholdSlider');
        if (slider && Number(slider.value) !== num) slider.value = String(num);
    }

    /**
     * Initialize UI state
     */
    initializeUI() {
        this.updateMetricsDisplay();
        this.validateInput();
        
        // Add helpful placeholder text
        const queryInput = document.getElementById('queryInput');
        queryInput.placeholder = 'Enter your query here... (e.g., "Explain the benefits of cloud computing" or "Write a Python function to sort a list")';

        // Reflect the default router mode (Custom) in the mode-dependent UI.
        // The Jev/Compare options start disabled until the first /health
        // response confirms jev.configured is true. Until that first result
        // arrives we label them "checking..." rather than "not configured", so
        // a live Jev deployment does not briefly read as unavailable on load.
        this.setJevAvailability(false, 'live', { pending: true });
        this.updateRouterModeUI();
    }

    /**
     * Initialize educational features and interactions
     */
    initializeEducationalFeatures() {
        // Add educational callouts dynamically
        this.addEducationalCallouts();
        
        // Set up educational highlighting
        this.setupEducationalHighlighting();
        
        // Add sample queries for demonstration
        this.addSampleQueries();
        
        // Initialize architecture diagram interactions
        this.initializeArchitectureDiagram();
        
        console.log('Educational features initialized');
    }

    /**
     * Initialize architecture diagram interactions
     */
    initializeArchitectureDiagram() {
        // Add click handlers for architecture components
        const componentBoxes = document.querySelectorAll('.component-box, .provider-box');
        componentBoxes.forEach(box => {
            box.addEventListener('click', (e) => {
                this.handleArchitectureComponentClick(e.target);
            });
        });
        
        // Add educational demonstration mode
        this.addArchitectureDemoMode();
        
        console.log('Architecture diagram interactions initialized');
    }

    /**
     * Handle clicks on architecture diagram components
     */
    handleArchitectureComponentClick(element) {
        // Get the parent group to identify the component
        const parentGroup = element.closest('g');
        if (!parentGroup) return;
        
        const componentId = parentGroup.id;
        let componentInfo = '';
        
        switch (componentId) {
            case 'client-layer':
                componentInfo = 'Web Frontend: The user interface layer that provides a consistent experience regardless of which AI provider processes requests. Built with HTML, CSS, and JavaScript.';
                break;
            case 'cloudfront-layer':
                componentInfo = 'CloudFront: AWS Content Delivery Network that distributes the web application globally for fast loading times and improved user experience.';
                break;
            case 'api-gateway-layer':
                componentInfo = 'API Gateway: Manages all API requests with authentication, rate limiting, and request validation. Provides a single, secure entry point.';
                break;
            case 'lambda-router-layer':
                componentInfo = 'Lambda Router Engine: The core intelligence implementing health monitoring, circuit breakers, and intelligent routing to optimal providers. It now also hosts the Jev router: in jev and compare modes it asks the external Jev decision service to choose a model, validates that choice with a local Routing Policy, and falls back to the custom router when needed.';
                break;
            case 'bedrock-layer':
                componentInfo = 'AWS Bedrock Converse API: The abstraction layer that provides a unified interface for all AI providers, eliminating provider-specific integration complexity.';
                break;
            case 'anthropic-provider':
                componentInfo = 'Anthropic Claude: Advanced reasoning and analysis capabilities with models optimized for different use cases and performance requirements.';
                break;
            case 'openai-provider':
                componentInfo = 'OpenAI GPT: gpt-oss-20b models deliver performance comparable to and surpassing leading alternatives, particularly in coding, scientific analysis, and mathematical reasoning tasks.';
                break;
            case 'nova-provider':
                componentInfo = 'AWS Nova: Cost-effective models optimized for AWS integration with multiple performance and cost options.';
                break;
            case 'monitoring-layer':
                componentInfo = 'CloudWatch: Comprehensive monitoring and logging service providing real-time visibility into system performance and behavior.';
                break;
            case 'jev-router-layer':
                componentInfo = 'Jev Router: Alternative routing path used in jev and compare modes. It sends the query and its characteristics to the external Jev decision service, then validates the answer with the Routing Policy before using it. Falls back to the Custom Router when the answer is unusable.';
                break;
            case 'jev-api-layer':
                componentInfo = 'Jev API: External decision service. It returns a routing decision only and does not run the model. Query text is sent to TypeSafe when the Jev or Compare modes are used.';
                break;
            case 'jev-secret-layer':
                componentInfo = 'Jev Secret: The TypeSafe API key, stored server-side in SSM Parameter Store or Secrets Manager. It is read server-side to authorise the Jev call and is never exposed to the browser.';
                break;
            default:
                componentInfo = 'Click on different components to learn about their role in the provider-agnostic architecture.';
        }
        
        this.showToast(`🏗️ ${componentInfo}`, 'info', 8000);
        
        // Highlight the clicked component
        element.classList.add('active');
        setTimeout(() => {
            element.classList.remove('active');
        }, 3000);
    }

    /**
     * Add architecture demonstration mode
     */
    addArchitectureDemoMode() {
        // Add demo control button
        const architectureSection = document.querySelector('.architecture-section');
        const demoButton = document.createElement('button');
        demoButton.className = 'demo-flow-btn';
        demoButton.textContent = '▶️ Demonstrate Data Flow';
        demoButton.style.cssText = `
            margin: 15px 0;
            padding: 10px 20px;
            background: var(--info-color);
            color: white;
            border: none;
            border-radius: var(--border-radius);
            font-weight: 600;
            cursor: pointer;
            transition: var(--transition);
        `;
        
        demoButton.addEventListener('click', () => {
            this.demonstrateArchitectureFlow();
        });
        
        demoButton.addEventListener('mouseover', () => {
            demoButton.style.background = '#1976D2';
            demoButton.style.transform = 'translateY(-1px)';
        });
        
        demoButton.addEventListener('mouseout', () => {
            demoButton.style.background = 'var(--info-color)';
            demoButton.style.transform = 'translateY(0)';
        });
        
        architectureSection.querySelector('.section-header').appendChild(demoButton);
    }

    /**
     * Demonstrate complete architecture flow
     */
    demonstrateArchitectureFlow() {
        this.showToast('🎬 Demonstrating complete request flow through provider-agnostic architecture...', 'info', 3000);
        
        const steps = [
            { selector: '#client-layer .component-box', message: '1️⃣ User submits query through web interface' },
            { selector: '#cloudfront-layer .component-box', message: '2️⃣ CloudFront delivers optimized content globally' },
            { selector: '#api-gateway-layer .component-box', message: '3️⃣ API Gateway validates and routes request' },
            { selector: '#lambda-router-layer .component-box', message: '4️⃣ Router analyzes request and selects optimal provider' },
            { selector: '#bedrock-layer .component-box', message: '5️⃣ Bedrock Converse API abstracts provider differences' },
            { selector: '#anthropic-provider .provider-box, #openai-provider .provider-box, #nova-provider .provider-box', message: '6️⃣ AI provider processes request (Anthropic, OpenAI, or Nova)' },
            { selector: '#monitoring-layer .component-box', message: '📊 CloudWatch monitors entire flow for observability' }
        ];
        
        steps.forEach((step, index) => {
            setTimeout(() => {
                // Highlight components
                const elements = document.querySelectorAll(step.selector);
                elements.forEach(el => el.classList.add('active'));
                
                // Show step message
                this.showToast(step.message, 'info', 2500);
                
                // Remove highlight after delay
                setTimeout(() => {
                    elements.forEach(el => el.classList.remove('active'));
                }, 2000);
                
            }, index * 1500);
        });
        
        // Final message
        setTimeout(() => {
            this.showToast('✨ Complete! This demonstrates how provider-agnostic architecture maintains consistent behavior regardless of which AI service processes the request.', 'success', 6000);
        }, steps.length * 1500);
    }

    /**
     * Add educational callout boxes to sections
     */
    addEducationalCallouts() {
        // Add callout to query section
        const querySection = document.querySelector('.query-section');
        const queryCallout = document.createElement('div');
        queryCallout.className = 'educational-callout';
        queryCallout.innerHTML = `
            <h4>🔍 What to Watch For</h4>
            <p>Notice how the same interface works regardless of which provider processes your request. This demonstrates the power of abstraction in system design!</p>
        `;
        querySection.appendChild(queryCallout);

        // Add callout to provider status section
        const providerSection = document.querySelector('.provider-status-section');
        const providerCallout = document.createElement('div');
        providerCallout.className = 'educational-callout';
        providerCallout.innerHTML = `
            <h4>⚡ Intelligent Routing</h4>
            <p>The system continuously monitors provider health and automatically routes requests to the best available option. Watch the status indicators change in real-time!</p>
        `;
        providerSection.appendChild(providerCallout);

        // Add callout to metrics section
        const metricsSection = document.querySelector('.metrics-section');
        const metricsCallout = document.createElement('div');
        metricsCallout.className = 'educational-callout';
        metricsCallout.innerHTML = `
            <h4>📈 Load Balancing in Action</h4>
            <p>Observe how queries are distributed across providers. The system balances load while considering factors like performance, cost, and availability.</p>
        `;
        metricsSection.appendChild(metricsCallout);
    }

    /**
     * Set up educational highlighting effects
     */
    setupEducationalHighlighting() {
        // Highlight provider cards when they're selected
        this.originalHighlightActiveProvider = this.highlightActiveProvider;
        this.highlightActiveProvider = (provider) => {
            this.originalHighlightActiveProvider(provider);
            
            // Add educational highlighting
            const providerCard = document.querySelector(`[data-provider="${provider.toLowerCase()}"]`);
            if (providerCard) {
                providerCard.classList.add('educational-highlight');
                
                // Show educational toast
                this.showToast(`🎯 Routing Decision: ${provider} selected based on health and performance metrics`, 'info', 5000);
                
                // Remove highlight after animation
                setTimeout(() => {
                    providerCard.classList.remove('educational-highlight');
                }, 4000);
            }
        };
    }

    /**
     * Add sample queries for educational demonstration
     */
    addSampleQueries() {
        const sampleQueries = [
            "Explain AWS Bedrock's LLM-as-Judge evaluation methodology and its advantages",
            "How do RPS, tokens per second, and concurrent users relate to throughput analysis?",
            "Describe how serverless architecture with Lambda and API Gateway enables automatic fallback",
            "What metrics are important for foundation model throughput analysis in enterprise deployments?",
            "How does AWS Bedrock's evaluation framework assess response quality, accuracy, and bias?"
        ];

        // Add sample query buttons
        const querySection = document.querySelector('.query-input-container');
        const sampleContainer = document.createElement('div');
        sampleContainer.className = 'sample-queries';
        sampleContainer.innerHTML = `
            <div class="sample-header">
                <span>💡 Try these sample queries:</span>
            </div>
            <div class="sample-buttons">
                ${sampleQueries.map(query => 
                    `<button class="sample-btn" data-query="${query}">${query}</button>`
                ).join('')}
            </div>
        `;

        querySection.appendChild(sampleContainer);

        // Add event listeners for sample queries
        sampleContainer.addEventListener('click', (e) => {
            if (e.target.classList.contains('sample-btn')) {
                const query = e.target.getAttribute('data-query');
                document.getElementById('queryInput').value = query;
                this.validateInput();
                this.showToast('Sample query loaded - click Submit to see provider-agnostic routing in action!', 'info');
            }
        });
    }

    /**
     * Validate input and enable/disable submit button
     */
    validateInput() {
        const queryInput = document.getElementById('queryInput');
        const submitBtn = document.getElementById('submitQuery');
        
        const isValid = queryInput.value.trim().length > 0 && !this.state.isLoading;
        submitBtn.disabled = !isValid;
        
        // Update character count (optional enhancement)
        const charCount = queryInput.value.length;
        if (charCount > 1800) {
            queryInput.style.borderColor = 'var(--warning-color)';
        } else {
            queryInput.style.borderColor = '';
        }
    }

    /**
     * Submit a query to the GenAI system
     */
    async submitQuery() {
        if (this.state.isLoading) return;

        const queryInput = document.getElementById('queryInput');
        const query = queryInput.value.trim();
        
        if (!query) {
            this.showToast('Please enter a query', 'warning');
            return;
        }

        this.setLoadingState(true);
        
        try {
            const requestData = {
                query: query,
                sessionId: this.config.sessionId,
                maxTokens: parseInt(document.getElementById('maxTokens').value),
                temperature: parseFloat(document.getElementById('temperature').value),
                timestamp: new Date().toISOString(),
                // Router mode selection (Jev comparison feature).
                router_mode: this.state.routerMode,
                // Per-request Jev confidence threshold from the UI slider.
                confidence_threshold: this.state.jev.confidenceThreshold
            };

            // In Compare mode, include execute_router only when a router is
            // selected (not the default "none"), so a routing-only comparison
            // does not trigger a generation.
            if (this.state.routerMode === 'compare' && this.state.executeRouter !== 'none') {
                requestData.execute_router = this.state.executeRouter;
            }

            console.log('Submitting query:', requestData);
            
            const startTime = Date.now();
            const response = await this.makeAPIRequest('/query', 'POST', requestData);
            const endTime = Date.now();
            
            // Calculate actual latency (including network time)
            const totalLatency = endTime - startTime;
            
            // Process the response
            this.handleQueryResponse(response, query, totalLatency);
            
            // Clear the input
            queryInput.value = '';
            this.validateInput();
            
        } catch (error) {
            console.error('Query submission failed:', error);
            this.handleQueryError(error, query);
        } finally {
            this.setLoadingState(false);
        }
    }

    /**
     * Handle successful query response
     */
    handleQueryResponse(response, originalQuery, totalLatency) {
        console.log('Query response received:', response);

        const comparison = response && response.routing_comparison;

        // Compare mode: render the side-by-side routing panels. A compare
        // response may or may not carry a generated answer depending on
        // whether an execute_router was named.
        if (comparison) {
            this.renderComparison(comparison, originalQuery);
        } else {
            // Non-compare responses never show the comparison section.
            this.hideComparison();
        }

        // A compare response without a generated answer carries no `response`
        // text or `metadata`. In that case we show only the routing comparison
        // and skip the answer display, metrics, history, and provider
        // highlighting, which all depend on metadata (Requirement 7.7).
        const hasGeneration = !!(response && response.metadata && response.response !== undefined);

        if (!hasGeneration) {
            // Routing-only comparison: hide the answer area so no stale answer
            // from a previous query lingers, and offer the run-with actions so
            // the user can execute the query with either router (Requirements
            // 7.7, 7.8).
            this.hideResponseSection();
            this.setComparisonRunActionsVisible(!!comparison);
            this.showToast('Routing comparison ready. Choose a router to run the query.', 'info');
            return;
        }

        // A generated answer is present. If it came from a compare request, the
        // routing comparison is shown above the answer and the run-with actions
        // are no longer needed.
        this.setComparisonRunActionsVisible(false);

        // Update response display
        this.displayResponse(response);

        // Update session metrics
        this.updateSessionMetrics(response, totalLatency);

        // Add to history
        this.addToHistory(originalQuery, response, totalLatency);

        // Highlight active provider
        this.highlightActiveProvider(response.metadata.provider);

        this.showToast(`Query processed by ${response.metadata.provider}`, 'success');
    }

    /**
     * Handle query errors
     */
    handleQueryError(error, originalQuery) {
        console.error('Query error:', error);
        
        let errorMessage = 'An error occurred while processing your query';
        
        if (error.message) {
            errorMessage = error.message;
        } else if (error.error && error.error.message) {
            errorMessage = error.error.message;
        }
        
        // Display error in response section
        this.displayError(errorMessage);
        
        // Add error to history
        this.addErrorToHistory(originalQuery, errorMessage);
        
        this.showToast(errorMessage, 'error');
    }

    /**
     * Display query response in the UI
     */
    displayResponse(response) {
        const responseSection = document.querySelector('.response-section');
        responseSection.style.display = 'block';
        
        // Update metadata
        document.getElementById('responseProvider').textContent = response.metadata.provider;
        document.getElementById('responseModel').textContent = response.metadata.model;
        document.getElementById('responseTokens').textContent = response.metadata.tokensUsed;
        document.getElementById('responseLatency').textContent = response.metadata.latencyMs + 'ms';
        document.getElementById('responseTimestamp').textContent = this.formatTimestamp(response.metadata.timestamp);
        
        // Update response text (reset any error colour from a prior failure)
        const responseText = document.getElementById('responseText');
        responseText.style.color = '';
        responseText.textContent = response.response;
        
        // Scroll to response
        responseSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    /**
     * Display error in the response section
     */
    displayError(errorMessage) {
        const responseSection = document.querySelector('.response-section');
        responseSection.style.display = 'block';
        
        // Clear metadata
        document.getElementById('responseProvider').textContent = 'Error';
        document.getElementById('responseModel').textContent = '--';
        document.getElementById('responseTokens').textContent = '--';
        document.getElementById('responseLatency').textContent = '--';
        document.getElementById('responseTimestamp').textContent = new Date().toLocaleString();
        
        // Display error message
        document.getElementById('responseText').textContent = `Error: ${errorMessage}`;
        document.getElementById('responseText').style.color = 'var(--error-color)';
        
        // Scroll to response
        responseSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    /**
     * Hide the answer/response section. Used for routing-only compare
     * responses, which carry a routing comparison but no generated answer
     * (Requirement 7.7).
     */
    hideResponseSection() {
        const responseSection = document.querySelector('.response-section');
        if (responseSection) {
            responseSection.style.display = 'none';
        }
    }

    /**
     * Hide the entire routing comparison section. Used for non-compare
     * responses so a stale comparison from a previous query never lingers.
     */
    hideComparison() {
        const comparisonSection = document.getElementById('comparisonSection');
        if (comparisonSection) {
            comparisonSection.hidden = true;
        }
    }

    /**
     * Render the side-by-side routing comparison (Requirement 7).
     *
     * All response-derived strings (model IDs, reasoning steps, fallback
     * reasons) are inserted with textContent, never innerHTML, because they
     * originate from an external service and must not be interpreted as markup
     * (XSS safety, design "Safe rendering").
     *
     * @param {object} comparison The `routing_comparison` object from the
     *   response: `{ agree, custom, jev }`.
     * @param {string} originalQuery The query that produced this comparison,
     *   stored so the run-with actions can resend it.
     */
    renderComparison(comparison, originalQuery) {
        const comparisonSection = document.getElementById('comparisonSection');
        if (!comparisonSection || !comparison) return;

        // Remember the query so "Run with Custom"/"Run with Jev" can resend it.
        this.state.lastComparisonQuery = originalQuery;

        comparisonSection.hidden = false;

        // Agreement banner: icon + text label + colour (colour is never the
        // only signal, Requirement 7.4). The data-agreement attribute drives
        // the distinct highlight styling (Requirement 7.3).
        const agree = comparison.agree === true;
        const agreementEl = document.getElementById('comparisonAgreement');
        const agreementIcon = document.getElementById('comparisonAgreementIcon');
        const agreementText = document.getElementById('comparisonAgreementText');
        if (agreementEl) {
            agreementEl.hidden = false;
            agreementEl.setAttribute('data-agreement', agree ? 'agree' : 'disagree');
        }
        if (agreementIcon) {
            agreementIcon.textContent = agree ? '✅' : '⚠️';
        }
        if (agreementText) {
            agreementText.textContent = agree ? 'Routers agree' : 'Routers disagree';
        }

        // Render each panel.
        this.renderComparisonPanel('custom', comparison.custom);
        this.renderComparisonPanel('jev', comparison.jev);

        // The run-with actions (shown only for a routing-only comparison) are
        // toggled by the caller via setComparisonRunActionsVisible, since only
        // the caller knows whether this response carried a generated answer.
        comparisonSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    /**
     * Render a single comparison panel (Custom or Jev).
     *
     * @param {'custom'|'jev'} router Which panel to populate.
     * @param {object} result The per-router Routing_Result from the comparison.
     */
    renderComparisonPanel(router, result) {
        if (!result) return;

        const isJev = (router === 'jev');
        const cap = isJev ? 'Jev' : 'Custom';

        const modelEl = document.getElementById(`comparison${cap}Model`);
        const confidenceEl = document.getElementById(`comparison${cap}Confidence`);
        const latencyEl = document.getElementById(`comparison${cap}Latency`);
        const reasoningEl = document.getElementById(`comparison${cap}Reasoning`);

        // Model and provider. All external strings via textContent only.
        if (modelEl) {
            const modelId = (result.model_id !== undefined && result.model_id !== null)
                ? String(result.model_id) : '--';
            const provider = (result.provider !== undefined && result.provider !== null && result.provider !== '')
                ? String(result.provider) : '';
            modelEl.textContent = provider ? `${modelId} (${provider})` : modelId;
        }

        if (confidenceEl) {
            confidenceEl.textContent = this.formatConfidence(result.confidence);
        }

        if (latencyEl) {
            const latency = Number(result.latency_ms);
            latencyEl.textContent = Number.isFinite(latency) ? `${Math.round(latency)}ms` : '--';
        }

        // Reasoning steps: rebuild the list with textContent-only <li> nodes.
        if (reasoningEl) {
            reasoningEl.textContent = '';
            const steps = Array.isArray(result.reasoning) ? result.reasoning : [];
            if (steps.length === 0) {
                const li = document.createElement('li');
                li.textContent = 'No reasoning steps provided.';
                reasoningEl.appendChild(li);
            } else {
                steps.forEach(step => {
                    const li = document.createElement('li');
                    li.textContent = String(step);
                    reasoningEl.appendChild(li);
                });
            }
        }

        // Jev-only decorations: fallback label, recorded-sample label, and
        // the "Jev's assessment" block (always shown so Jev's own confidence and
        // per-model probabilities are visible even when the policy fell back).
        if (isJev) {
            this.renderJevPanelLabels(result);
            this.renderJevAssessment(result);
        }
    }

    /**
     * Render a "Jev's assessment" block in the Jev panel.
     *
     * This always shows what Jev itself judged -- its own confidence and its
     * per-model probability distribution -- separately from the final routed
     * decision. On a fallback the final Model/Confidence rows reflect the Custom
     * router that was actually used, while this block preserves Jev's view so
     * the two routers can be compared even when Jev's pick was not taken.
     *
     * All values are inserted with textContent; nothing from the response is
     * treated as markup.
     *
     * @param {object} result The Jev Routing_Result.
     */
    renderJevAssessment(result) {
        const panel = document.getElementById('comparisonPanelJev');
        if (!panel) return;

        // Rebuild a single managed container each render so stale rows do not
        // accumulate across queries.
        let block = document.getElementById('comparisonJevAssessment');
        if (!block) {
            block = document.createElement('div');
            block.id = 'comparisonJevAssessment';
            block.className = 'jev-assessment';
            // Place it just above the reasoning section if present, else append.
            const reasoning = panel.querySelector('.comparison-reasoning');
            if (reasoning && reasoning.parentNode === panel) {
                panel.insertBefore(block, reasoning);
            } else {
                panel.appendChild(block);
            }
        }
        block.textContent = '';

        const heading = document.createElement('h4');
        heading.className = 'jev-assessment-title';
        heading.textContent = "Jev's assessment";
        block.appendChild(heading);

        // Jev's own confidence (distinct from the final routed confidence, which
        // may come from the Custom router on a fallback).
        const jevConf = document.createElement('p');
        jevConf.className = 'jev-assessment-confidence';
        const jc = (result.jev_confidence !== undefined && result.jev_confidence !== null)
            ? this.formatConfidence(result.jev_confidence)
            : 'n/a';
        jevConf.textContent = `Jev confidence: ${jc}`;
        block.appendChild(jevConf);

        // Whether Jev's own pick was used or the router fell back.
        const used = document.createElement('p');
        used.className = 'jev-assessment-used';
        used.textContent = (result.router_used === 'jev')
            ? "Jev's choice was used."
            : "Jev's choice was not used (fell back to the Custom router).";
        block.appendChild(used);

        // Per-model probability distribution, sorted high to low. Always shown
        // when Jev returned one, regardless of fallback.
        const probs = (result.probabilities && typeof result.probabilities === 'object')
            ? result.probabilities : {};
        const entries = Object.keys(probs).map(k => [k, Number(probs[k])])
            .filter(([, v]) => Number.isFinite(v))
            .sort((a, b) => b[1] - a[1]);

        if (entries.length > 0) {
            const probTitle = document.createElement('p');
            probTitle.className = 'jev-assessment-probs-title';
            probTitle.textContent = 'Model probabilities (Jev):';
            block.appendChild(probTitle);

            const list = document.createElement('ul');
            list.className = 'jev-assessment-probs';
            entries.forEach(([modelId, value]) => {
                const li = document.createElement('li');
                li.textContent = `${modelId}: ${(Math.max(0, Math.min(1, value)) * 100).toFixed(1)}%`;
                list.appendChild(li);
            });
            block.appendChild(list);
        } else {
            const none = document.createElement('p');
            none.className = 'jev-assessment-probs-title';
            none.textContent = 'Model probabilities (Jev): not available';
            block.appendChild(none);
        }
    }

    /**
     * Render the Jev panel's fallback and recorded-mode labels.
     *
     * - When `fallback` is true, show "Fallback to Custom" and append the
     *   fallback reason (Requirement 7.5).
     * - In recorded mode, label the result "recorded sample, not live"
     *   (Requirement 15.3). The label is created via DOM/textContent so no
     *   external string is ever interpreted as markup.
     *
     * @param {object} result The Jev Routing_Result.
     */
    renderJevPanelLabels(result) {
        const fallbackLabel = document.getElementById('comparisonJevFallbackLabel');
        if (fallbackLabel) {
            const isFallback = result.fallback === true;
            fallbackLabel.hidden = !isFallback;
            if (isFallback) {
                const reason = (result.fallback_reason !== undefined && result.fallback_reason !== null && result.fallback_reason !== '')
                    ? String(result.fallback_reason) : null;
                fallbackLabel.textContent = reason
                    ? `Fallback to Custom: ${reason}`
                    : 'Fallback to Custom';
            } else {
                // Reset to the static label for the next render.
                fallbackLabel.textContent = 'Fallback to Custom';
            }
        }

        // Recorded-sample label. The markup has no dedicated element for this,
        // so manage a single label node inside the Jev panel's title area.
        const panel = document.getElementById('comparisonPanelJev');
        if (!panel) return;

        const recorded = (result.mode === 'recorded') || (this.state.jev.mode === 'recorded');
        let recordedLabel = document.getElementById('comparisonJevRecordedLabel');

        if (recorded) {
            if (!recordedLabel) {
                recordedLabel = document.createElement('p');
                recordedLabel.id = 'comparisonJevRecordedLabel';
                recordedLabel.className = 'comparison-fallback-label';
                // Insert just after the panel title so it reads with the header.
                const title = document.getElementById('comparisonJevTitle');
                if (title && title.parentNode === panel) {
                    title.insertAdjacentElement('afterend', recordedLabel);
                } else {
                    panel.insertBefore(recordedLabel, panel.firstChild);
                }
            }
            recordedLabel.hidden = false;
            recordedLabel.textContent = 'recorded sample, not live';
        } else if (recordedLabel) {
            recordedLabel.hidden = true;
        }
    }

    /**
     * Format a confidence value in [0, 1] as a percentage string, defensively
     * handling missing or out-of-range values.
     */
    formatConfidence(value) {
        const num = Number(value);
        if (!Number.isFinite(num)) return '--';
        const clamped = Math.max(0, Math.min(1, num));
        return `${Math.round(clamped * 100)}%`;
    }

    /**
     * Show or hide the run-with actions on the comparison section.
     *
     * @param {boolean} show Whether to reveal the "Run with Custom"/"Run with
     *   Jev" actions.
     */
    setComparisonRunActionsVisible(show) {
        const runActions = document.getElementById('comparisonRunActions');
        if (runActions) {
            runActions.hidden = !show;
        }
    }

    /**
     * Resend the stored comparison query in Compare mode with the chosen
     * execute_router, so exactly one model runs without re-asking for the
     * query text (Requirement 7.8). Both routers are re-evaluated server-side,
     * so the Jev result in the new response may differ from the previous one.
     *
     * @param {'custom'|'jev'} router Which router should execute the query.
     */
    async runComparisonWith(router) {
        if (this.state.isLoading) return;

        const query = this.state.lastComparisonQuery;
        if (!query) {
            this.showToast('No comparison query to run. Submit a query first.', 'warning');
            return;
        }

        this.setLoadingState(true);

        try {
            const requestData = {
                query: query,
                sessionId: this.config.sessionId,
                maxTokens: parseInt(document.getElementById('maxTokens').value),
                temperature: parseFloat(document.getElementById('temperature').value),
                timestamp: new Date().toISOString(),
                router_mode: 'compare',
                execute_router: router,
                confidence_threshold: this.state.jev.confidenceThreshold
            };

            this.showToast(`Running the comparison query with the ${router} router...`, 'info');

            const startTime = Date.now();
            const response = await this.makeAPIRequest('/query', 'POST', requestData);
            const endTime = Date.now();

            this.handleQueryResponse(response, query, endTime - startTime);
        } catch (error) {
            console.error('Run-with request failed:', error);
            this.handleQueryError(error, query);
        } finally {
            this.setLoadingState(false);
        }
    }

    /**
     * Update session metrics
     */
    updateSessionMetrics(response, totalLatency) {
        const metrics = this.state.sessionMetrics;
        
        metrics.totalQueries++;
        metrics.totalTokens += response.metadata.tokensUsed;
        
        // Update average latency
        const currentAvg = metrics.averageLatency;
        metrics.averageLatency = Math.round(
            (currentAvg * (metrics.totalQueries - 1) + response.metadata.latencyMs) / metrics.totalQueries
        );
        
        // Update provider distribution
        const provider = response.metadata.provider.toLowerCase();
        if (metrics.providerDistribution[provider] !== undefined) {
            metrics.providerDistribution[provider]++;
        }
        
        this.updateMetricsDisplay();
    }

    /**
     * Update metrics display in the UI
     */
    updateMetricsDisplay() {
        const metrics = this.state.sessionMetrics;
        
        document.getElementById('totalQueries').textContent = metrics.totalQueries;
        document.getElementById('avgLatency').textContent = metrics.averageLatency > 0 ? 
            metrics.averageLatency + 'ms' : '--ms';
        document.getElementById('totalTokens').textContent = metrics.totalTokens;
        
        // Update provider distribution
        const distributionItems = document.querySelectorAll('.distribution-item .provider-count');
        distributionItems[0].textContent = metrics.providerDistribution.anthropic;
        distributionItems[1].textContent = metrics.providerDistribution.openai;
        distributionItems[2].textContent = metrics.providerDistribution.nova;
    }

    /**
     * Add query to session history
     */
    addToHistory(query, response, totalLatency) {
        const historyItem = {
            id: Date.now(),
            timestamp: new Date(),
            query: query,
            response: response.response,
            provider: response.metadata.provider,
            model: response.metadata.model,
            tokens: response.metadata.tokensUsed,
            latency: response.metadata.latencyMs,
            totalLatency: totalLatency
        };
        
        this.state.queryHistory.unshift(historyItem); // Add to beginning
        
        // Limit history to 50 items
        if (this.state.queryHistory.length > 50) {
            this.state.queryHistory = this.state.queryHistory.slice(0, 50);
        }
        
        this.updateHistoryDisplay();
    }

    /**
     * Add error to session history
     */
    addErrorToHistory(query, errorMessage) {
        const historyItem = {
            id: Date.now(),
            timestamp: new Date(),
            query: query,
            error: errorMessage,
            provider: 'Error',
            model: '--',
            tokens: 0,
            latency: 0,
            totalLatency: 0
        };
        
        this.state.queryHistory.unshift(historyItem);
        this.updateHistoryDisplay();
    }

    /**
     * Update history display in the UI
     */
    updateHistoryDisplay() {
        const historyList = document.getElementById('historyList');
        
        if (this.state.queryHistory.length === 0) {
            historyList.innerHTML = `
                <div class="history-empty">
                    <p>No queries submitted yet. Start by entering a query above.</p>
                </div>
            `;
            return;
        }
        
        historyList.innerHTML = this.state.queryHistory.map(item => `
            <div class="history-item">
                <div class="history-header">
                    <span class="history-timestamp">${item.timestamp.toLocaleString()}</span>
                    <span class="history-provider ${item.error ? 'error' : ''}">${item.provider}</span>
                </div>
                <div class="history-query">"${this.truncateText(item.query, 100)}"</div>
                ${item.error ? 
                    `<div class="history-error" style="color: var(--error-color); font-size: 0.9rem;">Error: ${item.error}</div>` :
                    `<div class="history-metrics">
                        <span>Model: ${item.model}</span>
                        <span>Tokens: ${item.tokens}</span>
                        <span>Latency: ${item.latency}ms</span>
                        <span>Total: ${item.totalLatency}ms</span>
                    </div>`
                }
            </div>
        `).join('');
    }

    /**
     * Clear session history
     */
    clearHistory() {
        if (this.state.queryHistory.length === 0) {
            this.showToast('History is already empty', 'info');
            return;
        }
        
        if (confirm('Are you sure you want to clear the session history?')) {
            this.state.queryHistory = [];
            this.updateHistoryDisplay();
            this.showToast('Session history cleared', 'success');
        }
    }

    /**
     * Highlight the active provider during query processing
     */
    highlightActiveProvider(provider) {
        // Remove previous highlights
        document.querySelectorAll('.provider-card').forEach(card => {
            card.classList.remove('active');
        });
        
        // Highlight current provider card
        const providerCard = document.querySelector(`[data-provider="${provider.toLowerCase()}"]`);
        if (providerCard) {
            providerCard.classList.add('active');
            
            // Remove highlight after 3 seconds
            setTimeout(() => {
                providerCard.classList.remove('active');
            }, 3000);
        }
        
        // Highlight in architecture diagram
        this.highlightArchitectureFlow(provider);
    }

    /**
     * Highlight data flow in architecture diagram
     */
    highlightArchitectureFlow(provider) {
        // Remove previous highlights
        document.querySelectorAll('.component-box, .provider-box, .flow-line, .provider-line').forEach(element => {
            element.classList.remove('active');
        });
        
        // Highlight the complete flow
        const flowElements = [
            '#client-layer .component-box',
            '#cloudfront-layer .component-box', 
            '#api-gateway-layer .component-box',
            '#lambda-router-layer .component-box',
            '#bedrock-layer .component-box'
        ];
        
        flowElements.forEach((selector, index) => {
            setTimeout(() => {
                const element = document.querySelector(selector);
                if (element) {
                    element.classList.add('active');
                }
            }, index * 200); // Stagger the highlights
        });
        
        // Highlight request flow arrows
        setTimeout(() => {
            document.querySelectorAll('#request-flow .flow-line').forEach(line => {
                line.classList.add('active');
            });
        }, 1000);
        
        // Highlight specific provider
        setTimeout(() => {
            const providerBox = document.querySelector(`#${provider.toLowerCase()}-provider .provider-box`);
            const providerLine = document.querySelector(`#${provider.toLowerCase()}-line`);
            
            if (providerBox) {
                providerBox.classList.add('active');
            }
            if (providerLine) {
                providerLine.classList.add('active');
            }
        }, 1200);
        
        // Clear all highlights after animation
        setTimeout(() => {
            document.querySelectorAll('.component-box, .provider-box, .flow-line, .provider-line').forEach(element => {
                element.classList.remove('active');
            });
        }, 4000);
    }

    /**
     * Check provider health status
     */
    async checkProviderHealth() {
        try {
            console.log('Checking provider health...');
            const healthData = await this.makeAPIRequest('/health', 'GET');

            // Jev router configuration state (Jev comparison feature). The
            // health endpoint returns a `jev` object when the feature is
            // available. A missing object or configured=false means Jev is not
            // configured, so the Jev and Compare modes stay disabled.
            this.applyJevHealth(healthData && healthData.jev);

            if (healthData && healthData.providers) {
                this.updateProviderStatus(healthData.providers);
            } else {
                // Backend returned a response without provider data (e.g. an
                // initialization error). Surface it instead of silently leaving
                // the cards stuck on "Checking...".
                console.warn('Health response missing providers:', healthData);
                Object.keys(this.state.providerStatus).forEach(provider => {
                    this.state.providerStatus[provider] = {
                        status: 'unknown',
                        latency: 0,
                        successRate: 0
                    };
                });
                this.updateProviderStatusDisplay();
            }
        } catch (error) {
            console.error('Health check failed:', error);

            // The health call failed: keep Custom selected and leave Jev and
            // Compare disabled and labelled "not configured" (Requirement 8.7).
            this.applyJevHealth(null);

            // Set all providers to unknown status
            Object.keys(this.state.providerStatus).forEach(provider => {
                this.state.providerStatus[provider] = {
                    status: 'unknown',
                    latency: 0,
                    successRate: 0
                };
            });
            this.updateProviderStatusDisplay();
        }
    }

    /**
     * Apply the Jev configuration state reported by the health endpoint.
     *
     * @param {object|null|false} jev The `jev` object from GET /health, or a
     *   falsy value when the feature is absent or the call failed. A truthy
     *   object with `configured === true` enables the Jev and Compare modes.
     */
    applyJevHealth(jev) {
        const configured = !!(jev && jev.configured === true);
        const mode = (jev && jev.mode === 'recorded') ? 'recorded' : 'live';
        this.state.jev.healthChecked = true;
        this.setJevAvailability(configured, mode);

        // On the first health result, sync the slider to the server's default
        // threshold so the UI starts in step with the deployed configuration.
        // The user can then override it per request by moving the slider.
        if (jev && typeof jev.confidence_threshold === 'number' && !this._thresholdInitialised) {
            this._thresholdInitialised = true;
            this.setConfidenceThreshold(jev.confidence_threshold);
        }
    }

    /**
     * Enable or disable the Jev-dependent router modes and refresh the
     * mode-dependent UI.
     *
     * When Jev is not configured, the Jev and Compare radios are disabled and
     * labelled "not configured". If the current selection was Jev or Compare
     * (for example a disabled option was somehow active), it is reset to Custom
     * so the selector never rests on an unavailable mode (Requirements 1.1,
     * 1.2, 8.4, 8.7).
     */
    setJevAvailability(configured, mode, options) {
        this.state.jev.configured = configured;
        this.state.jev.mode = mode;

        const pending = !!(options && options.pending);

        // Mark the Jev architecture nodes "not configured" to match the health state.
        this.updateArchitectureJevState(configured);

        const jevRadio = document.getElementById('routerModeJev');
        const compareRadio = document.getElementById('routerModeCompare');
        const jevLabel = document.getElementById('jevNotConfiguredLabel');
        const compareLabel = document.getElementById('compareNotConfiguredLabel');

        if (jevRadio) jevRadio.disabled = !configured;
        if (compareRadio) compareRadio.disabled = !configured;

        // Before the first health result, show a neutral "checking..." label
        // instead of "not configured"; afterwards show "not configured" only
        // when Jev really is unavailable.
        const labelText = pending ? 'checking\u2026' : 'not configured';
        if (jevLabel) {
            jevLabel.textContent = labelText;
            jevLabel.hidden = configured;
        }
        if (compareLabel) {
            compareLabel.textContent = labelText;
            compareLabel.hidden = configured;
        }

        // If the active mode is no longer available, fall back to Custom.
        if (!configured && (this.state.routerMode === 'jev' || this.state.routerMode === 'compare')) {
            const customRadio = document.getElementById('routerModeCustom');
            if (customRadio) customRadio.checked = true;
            this.setRouterMode('custom');
            return;
        }

        this.updateRouterModeUI();
    }

    /**
     * Toggle the "not configured" tags on the Jev architecture diagram nodes.
     *
     * Driven by the same GET /health jev.configured state tracked in
     * this.state.jev (set via applyJevHealth). When Jev is not configured the
     * Jev Router, Jev API, and Jev Secret nodes show a "not configured" tag;
     * when configured the tags are hidden (Requirement 12.4).
     *
     * @param {boolean} configured Whether Jev is configured per the health check.
     */
    updateArchitectureJevState(configured) {
        const tagIds = ['jevRouterNotConfigured', 'jevApiNotConfigured', 'jevSecretNotConfigured'];
        tagIds.forEach((id) => {
            const tag = document.getElementById(id);
            if (tag) {
                // SVG <text> uses the visibility attribute rather than hidden.
                tag.setAttribute('visibility', configured ? 'hidden' : 'visible');
            }
        });
    }

    /**
     * Record the selected router mode and refresh the mode-dependent UI.
     */
    setRouterMode(mode) {
        this.state.routerMode = mode;
        this.updateRouterModeUI();
    }

    /**
     * Reveal or hide the mode-dependent controls: the Execute-with group (only
     * in Compare mode), the privacy notice (Jev and Compare, live mode), and
     * the recorded-mode notice (Jev and Compare when jev.mode is "recorded").
     */
    updateRouterModeUI() {
        const mode = this.state.routerMode;
        const usesJev = (mode === 'jev' || mode === 'compare');

        // Execute-with group is only relevant in Compare mode.
        const executeContainer = document.getElementById('executeRouterGroupContainer');
        if (executeContainer) {
            executeContainer.hidden = (mode !== 'compare');
        }
        // Leaving Compare mode clears any pending execute-router selection.
        if (mode !== 'compare') {
            const noneRadio = document.getElementById('executeRouterNone');
            if (noneRadio) noneRadio.checked = true;
            this.state.executeRouter = 'none';
        }

        // Privacy / recorded notices. In recorded mode the query is not sent,
        // so show the recorded notice instead of the privacy notice.
        const recorded = (this.state.jev.mode === 'recorded');
        const privacyNotice = document.getElementById('jevPrivacyNotice');
        const recordedNotice = document.getElementById('jevRecordedNotice');
        if (privacyNotice) {
            privacyNotice.hidden = !(usesJev && !recorded);
        }
        if (recordedNotice) {
            recordedNotice.hidden = !(usesJev && recorded);
        }
    }

    /**
     * Update provider status from health check
     */
    updateProviderStatus(providers) {
        Object.keys(providers).forEach(provider => {
            if (this.state.providerStatus[provider]) {
                this.state.providerStatus[provider] = {
                    status: this.normalizeStatus(providers[provider].status),
                    latency: providers[provider].latency || 0,
                    successRate: providers[provider].successRate || 0
                };
            }
        });
        
        this.updateProviderStatusDisplay();
    }

    /**
     * Normalize backend health status vocabulary to the values the UI understands.
     * The backend HealthStatus enum emits 'unhealthy', while the UI styles and
     * status text are keyed on 'unavailable'.
     */
    normalizeStatus(status) {
        if (status === 'unhealthy') return 'unavailable';
        return status || 'unknown';
    }

    /**
     * Update provider status display in the UI
     */
    updateProviderStatusDisplay() {
        Object.keys(this.state.providerStatus).forEach(provider => {
            const card = document.querySelector(`[data-provider="${provider}"]`);
            if (!card) return;
            
            const status = this.state.providerStatus[provider];
            const statusIndicator = card.querySelector('.status-indicator');
            const statusText = card.querySelector('.status-text');
            const metrics = card.querySelectorAll('.metric-value');
            
            // Update status indicator
            statusIndicator.setAttribute('data-status', status.status);
            
            // Update status text
            const statusTexts = {
                healthy: 'Healthy',
                degraded: 'Degraded',
                unavailable: 'Unavailable',
                unknown: 'Checking...'
            };
            statusText.textContent = statusTexts[status.status] || 'Unknown';
            
            // Update metrics
            if (metrics.length >= 2) {
                metrics[0].textContent = status.latency > 0 ? status.latency + 'ms' : '--ms';
                metrics[1].textContent = status.successRate > 0 ? Math.round(status.successRate) + '%' : '--%';
            }
        });
        
        // Update architecture diagram
        this.updateArchitectureDiagramStatus();
    }

    /**
     * Update architecture diagram based on provider status
     */
    updateArchitectureDiagramStatus() {
        Object.keys(this.state.providerStatus).forEach(provider => {
            const providerBox = document.querySelector(`#${provider}-provider .provider-box`);
            if (!providerBox) return;
            
            // Remove all status classes
            providerBox.classList.remove('healthy', 'degraded', 'unavailable', 'simulated-failure');
            
            // Check if this provider has simulated failure
            if (this.state.failureSimulations[provider]) {
                providerBox.classList.add('simulated-failure');
            } else {
                // Add status class based on actual health
                const status = this.state.providerStatus[provider].status;
                if (status && status !== 'unknown') {
                    providerBox.classList.add(status);
                }
            }
        });
    }

    /**
     * Toggle admin panel visibility
     */
    toggleAdminPanel() {
        const adminSection = document.querySelector('.admin-section');
        const toggleBtn = document.getElementById('toggleAdminPanel');
        
        if (adminSection.style.display === 'none' || !adminSection.style.display) {
            adminSection.style.display = 'block';
            toggleBtn.textContent = 'Hide Instructor Controls';
            
            // Add educational context
            this.showToast('🎓 Instructor Controls: Use these toggles to simulate provider failures and demonstrate system resilience', 'info', 7000);
            
            // Add educational callout to admin section
            this.addAdminEducationalContent();
            
        } else {
            adminSection.style.display = 'none';
            toggleBtn.textContent = 'Show Instructor Controls';
            
            // Show current simulation status if any are active
            const simStatus = this.getSimulationStatus();
            if (simStatus.hasActiveSimulations) {
                this.showToast(`⚠️ ${simStatus.count} provider simulation(s) still active: ${simStatus.activeProviders.join(', ')}`, 'warning');
            }
        }
    }

    /**
     * Add educational content to admin section
     */
    addAdminEducationalContent() {
        const adminSection = document.querySelector('.admin-section');
        let educationalContent = adminSection.querySelector('.admin-educational-content');
        
        if (!educationalContent) {
            educationalContent = document.createElement('div');
            educationalContent.className = 'admin-educational-content';
            educationalContent.innerHTML = `
                <div class="educational-callout">
                    <h4>🎯 Teaching Objectives</h4>
                    <p><strong>Demonstrate Fault Tolerance:</strong> Toggle provider failures to show how the system automatically routes to healthy providers.</p>
                    <p><strong>Show Circuit Breaker Pattern:</strong> Observe how the system prevents requests to failed providers and recovers when they're restored.</p>
                    <p><strong>Illustrate Graceful Degradation:</strong> Even with multiple provider failures, the system continues to function with available resources.</p>
                </div>
                <div class="simulation-status">
                    <h4>📊 Current Simulation Status</h4>
                    <div id="simulationStatusDisplay">
                        <p>All providers operating normally</p>
                    </div>
                </div>
            `;
            
            adminSection.insertBefore(educationalContent, adminSection.querySelector('.admin-controls'));
        }
        
        this.updateSimulationStatusDisplay();
    }

    /**
     * Update simulation status display
     */
    updateSimulationStatusDisplay() {
        const statusDisplay = document.getElementById('simulationStatusDisplay');
        if (!statusDisplay) return;
        
        const simStatus = this.getSimulationStatus();
        
        if (simStatus.hasActiveSimulations) {
            statusDisplay.innerHTML = `
                <div class="active-simulations">
                    <p style="color: var(--error-color); font-weight: 600;">
                        🚨 Active Simulations: ${simStatus.activeProviders.join(', ')}
                    </p>
                    <p style="font-size: 0.9rem; color: var(--text-secondary);">
                        These providers are artificially marked as unavailable for educational demonstration.
                    </p>
                </div>
            `;
        } else {
            statusDisplay.innerHTML = `
                <p style="color: var(--success-color); font-weight: 600;">
                    ✅ All providers operating normally
                </p>
            `;
        }
    }

    /**
     * Toggle provider failure simulation
     */
    async toggleProviderSimulation(provider, enabled) {
        console.log(`${enabled ? 'Enabling' : 'Disabling'} failure simulation for ${provider}`);
        
        try {
            // Update local state
            this.state.failureSimulations[provider] = enabled;
            
            // Make API call to enable/disable simulation
            const endpoint = `/admin/simulate-failure`;
            const requestData = {
                provider: provider,
                enabled: enabled,
                sessionId: this.config.sessionId
            };
            
            await this.makeAPIRequest(endpoint, 'POST', requestData);
            
            // Update UI to reflect simulation state
            this.updateSimulationDisplay(provider, enabled);
            
            // Show educational toast
            if (enabled) {
                this.showToast(`🚨 Educational Demo: ${provider} failure simulation enabled. Watch how the system routes to other providers!`, 'warning', 6000);
            } else {
                this.showToast(`✅ ${provider} failure simulation disabled. Provider restored to normal operation.`, 'success');
            }
            
            // Trigger immediate health check to show the change
            setTimeout(() => this.checkProviderHealth(), 1000);
            
        } catch (error) {
            console.error(`Failed to toggle simulation for ${provider}:`, error);
            
            // Revert the toggle if API call failed
            const toggle = document.getElementById(`simulate${provider.charAt(0).toUpperCase() + provider.slice(1)}Failure`);
            if (toggle) {
                toggle.checked = !enabled;
            }
            this.state.failureSimulations[provider] = !enabled;
            
            this.showToast(`Failed to ${enabled ? 'enable' : 'disable'} ${provider} simulation: ${error.message}`, 'error');
        }
    }

    /**
     * Update simulation display in the UI
     */
    updateSimulationDisplay(provider, enabled) {
        const providerCard = document.querySelector(`[data-provider="${provider}"]`);
        if (!providerCard) return;
        
        // Add/remove simulation indicator
        let simulationBadge = providerCard.querySelector('.simulation-badge');
        
        if (enabled) {
            if (!simulationBadge) {
                simulationBadge = document.createElement('div');
                simulationBadge.className = 'simulation-badge';
                simulationBadge.textContent = 'SIMULATED FAILURE';
                providerCard.querySelector('.provider-header').appendChild(simulationBadge);
            }
            
            // Add visual styling for simulated failure
            providerCard.classList.add('simulated-failure');
            
            // Update status to unavailable
            const statusIndicator = providerCard.querySelector('.status-indicator');
            statusIndicator.setAttribute('data-status', 'unavailable');
            statusIndicator.querySelector('.status-text').textContent = 'Simulated Failure';
            
        } else {
            if (simulationBadge) {
                simulationBadge.remove();
            }
            
            // Remove visual styling
            providerCard.classList.remove('simulated-failure');
        }
    }

    /**
     * Reset all failure simulations
     */
    async resetSimulations() {
        console.log('Resetting all failure simulations...');
        
        try {
            // Reset all toggles
            const toggles = [
                document.getElementById('simulateAnthropicFailure'),
                document.getElementById('simulateOpenAIFailure'),
                document.getElementById('simulateNovaFailure')
            ];
            
            // Disable all simulations
            const resetPromises = [];
            Object.keys(this.state.failureSimulations).forEach(provider => {
                if (this.state.failureSimulations[provider]) {
                    resetPromises.push(this.toggleProviderSimulation(provider, false));
                }
            });
            
            // Wait for all resets to complete
            await Promise.all(resetPromises);
            
            // Reset toggle switches
            toggles.forEach(toggle => {
                if (toggle) toggle.checked = false;
            });
            
            // Clear all simulation displays
            Object.keys(this.state.failureSimulations).forEach(provider => {
                this.updateSimulationDisplay(provider, false);
                this.state.failureSimulations[provider] = false;
            });
            
            this.showToast('🔄 All failure simulations reset. System restored to normal operation.', 'success');
            
            // Trigger health check to refresh status
            setTimeout(() => this.checkProviderHealth(), 1000);
            
        } catch (error) {
            console.error('Failed to reset simulations:', error);
            this.showToast('Failed to reset some simulations. Please try individual toggles.', 'error');
        }
    }

    /**
     * Get current simulation status for educational display
     */
    getSimulationStatus() {
        const activeSimulations = Object.keys(this.state.failureSimulations)
            .filter(provider => this.state.failureSimulations[provider]);
        
        return {
            hasActiveSimulations: activeSimulations.length > 0,
            activeProviders: activeSimulations,
            count: activeSimulations.length
        };
    }

    /**
     * Set loading state
     */
    setLoadingState(isLoading) {
        this.state.isLoading = isLoading;
        
        const submitBtn = document.getElementById('submitQuery');
        const btnText = submitBtn.querySelector('.btn-text');
        const spinner = submitBtn.querySelector('.loading-spinner');
        
        if (isLoading) {
            btnText.textContent = 'Processing...';
            spinner.style.display = 'block';
            submitBtn.disabled = true;
        } else {
            btnText.textContent = 'Submit Query';
            spinner.style.display = 'none';
            this.validateInput(); // Re-enable if input is valid
        }
    }

    /**
     * Make API request with error handling and retries
     */
    async makeAPIRequest(endpoint, method = 'GET', data = null, retryCount = 0) {
        const url = this.config.apiBaseUrl + endpoint;
        
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-Session-ID': this.config.sessionId
            }
        };
        
        if (data) {
            options.body = JSON.stringify(data);
        }
        
        try {
            console.log(`Making ${method} request to ${url}`, data);
            
            const response = await fetch(url, options);
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `HTTP ${response.status}: ${response.statusText}`);
            }
            
            const responseData = await response.json();
            console.log('API response:', responseData);
            
            return responseData;
            
        } catch (error) {
            console.error(`API request failed (attempt ${retryCount + 1}):`, error);
            
            // Retry logic for network errors
            if (retryCount < this.config.maxRetries && 
                (error.name === 'TypeError' || error.message.includes('fetch'))) {
                
                console.log(`Retrying in ${this.config.retryDelay}ms...`);
                await this.delay(this.config.retryDelay);
                return this.makeAPIRequest(endpoint, method, data, retryCount + 1);
            }
            
            throw error;
        }
    }

    /**
     * Show toast notification
     */
    showToast(message, type = 'info', duration = 4000) {
        const container = document.getElementById('toastContainer');
        
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        
        container.appendChild(toast);
        
        // Auto-remove after duration
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, duration);
    }

    /**
     * Safely format a timestamp for display.
     *
     * The backend sends an ISO-8601 string in metadata.timestamp. Older
     * responses (or epoch-second numbers) are handled defensively: a numeric
     * epoch in seconds is converted to milliseconds, and anything unparseable
     * falls back to the current time instead of rendering "Invalid Date".
     */
    formatTimestamp(value) {
        let date;

        if (value === undefined || value === null || value === '') {
            date = new Date();
        } else if (typeof value === 'number') {
            // Epoch seconds (10 digits) vs milliseconds (13 digits)
            date = new Date(value < 1e12 ? value * 1000 : value);
        } else {
            date = new Date(value);
            // Numeric string epoch, e.g. "1730000000.123"
            if (isNaN(date.getTime()) && !isNaN(parseFloat(value))) {
                const num = parseFloat(value);
                date = new Date(num < 1e12 ? num * 1000 : num);
            }
        }

        if (isNaN(date.getTime())) {
            date = new Date();
        }

        return date.toLocaleString();
    }

    /**
     * Utility function to truncate text
     */
    truncateText(text, maxLength) {
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    /**
     * Utility function for delays
     */
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// Code samples for educational display
const CODE_SAMPLES = {
    'query-interface': {
        title: 'Query Interface - Provider-Agnostic API Call',
        code: `// Frontend makes identical API calls regardless of provider
async function submitQuery(query) {
    const response = await fetch(API_URL + '/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            query: query,
            sessionId: generateSessionId()
        })
    });
    
    const result = await response.json();
    
    // Response format is identical for ALL providers
    console.log('Provider:', result.metadata.provider);  // anthropic, openai, or nova
    console.log('Response:', result.response);
    console.log('Tokens:', result.metadata.tokensUsed);
    
    // Your application code never changes!
    return result;
}
`
    },
    'provider-status': {
        title: 'Health Monitoring - Real-time Provider Status',
        code: `def check_provider_health(provider):
    """
    Continuous health monitoring for intelligent routing
    """
    try:
        # Test provider with lightweight query
        start_time = time.time()
        response = bedrock.converse(
            modelId=get_test_model(provider),
            messages=[{"role": "user", "content": "test"}]
        )
        latency = (time.time() - start_time) * 1000
        
        # Update health metrics
        health_status[provider] = {
            'status': 'healthy',
            'latency': latency,
            'successRate': calculate_success_rate(provider),
            'lastCheck': time.time()
        }
        
        return health_status[provider]
        
    except Exception as e:
        # Mark provider as unhealthy
        health_status[provider] = {
            'status': 'unavailable',
            'error': str(e)
        }
        logger.warning(f"Provider {provider} health check failed")
`
    },
    'lambda-router': {
        title: 'Lambda Router Engine - Intelligent Model Selection',
        code: `"""
Lambda Router Engine - Core Intelligence

This module implements intelligent model selection and routing across
multiple GenAI providers (Anthropic Claude, OpenAI GPT, AWS Nova).

Key Features:
- Health-based routing with circuit breakers
- Load balancing across providers
- Performance-optimized model selection
- Two selectable routers: the built-in Custom router and the Jev router
- A "compare" mode that runs both routers on one health snapshot
- Comprehensive error handling
"""

def handle_query_request(params):
    """
    Dispatch on router_mode (custom | jev | compare).

    - custom (default): the Custom router picks a model directly.
    - jev: the Jev router asks the external Jev decision service, then a
      deterministic Routing Policy validates the choice and falls back to
      the Custom router when it is unusable.
    - compare: both routers run against the same health snapshot; the
      response carries a routing_comparison. A model runs only when
      execute_router names one.
    """
    mode = params.get("router_mode", "custom")
    if mode == "jev":
        return _handle_jev_mode(params)
    if mode == "compare":
        return _handle_compare_mode(params)
    return _handle_custom_mode(params)


def route_to_optimal_model(query, health_status):
    """
    Select the best model based on:
    1. Provider health and availability
    2. Query characteristics (length, complexity)
    3. Current load distribution
    4. Performance history
    """
    
    # Step 1: Filter healthy models
    healthy_models = [
        model for model in available_models
        if health_status[model.provider] == 'healthy'
    ]
    
    # Step 2: Score each model
    scores = {}
    for model in healthy_models:
        score = calculate_model_score(
            model=model,
            query_length=len(query),
            current_load=get_load(model),
            avg_latency=get_avg_latency(model)
        )
        scores[model] = score
    
    # Step 3: Select best model
    best_model = max(scores, key=scores.get)
    
    logger.info(f"Selected {best_model.name} with score {scores[best_model]}")
    
    return best_model


def calculate_model_score(model, query_length, current_load, avg_latency):
    """
    Calculate model suitability score based on multiple factors
    """
    # Base score from model capabilities
    capability_score = model.max_tokens / 1000
    
    # Adjust for current load (prefer less loaded models)
    load_penalty = current_load * 0.1
    
    # Adjust for performance (prefer faster models)
    latency_penalty = avg_latency / 1000
    
    # Query complexity matching
    if query_length > 1000:
        complexity_bonus = 0.2 if model.tier == 'advanced' else 0
    else:
        complexity_bonus = 0.2 if model.tier == 'fast' else 0
    
    final_score = capability_score - load_penalty - latency_penalty + complexity_bonus
    
    return final_score
`
    },
    'bedrock-adapter': {
        title: 'AWS Bedrock Converse API - Provider Abstraction',
        code: `"""
Bedrock Converse API Adapter - Unified Provider Interface

This adapter provides a single, consistent interface for all GenAI providers
through AWS Bedrock's Converse API, eliminating provider-specific code.

Supported Providers:
- Anthropic Claude (Claude 4.6 Sonnet)
- OpenAI GPT (GPT OSS 120B)
- AWS Nova (Pro, Lite, Micro)
"""

class BedrockConverseAdapter:
    """
    Unified adapter for all GenAI providers via Bedrock Converse API
    """
    
    def __init__(self, region_name='us-east-1'):
        self.bedrock = boto3.client('bedrock-runtime', region_name=region_name)
        self.models = self._initialize_models()
    
    def invoke_model(self, model_id, messages, max_tokens=1000, temperature=0.7):
        """
        Invoke any model using the unified Converse API
        
        This single method works identically for ALL providers!
        """
        try:
            # Unified API call - same for Anthropic, Meta, and Nova
            response = self.bedrock.converse(
                modelId=model_id,
                messages=messages,
                inferenceConfig={
                    'maxTokens': max_tokens,
                    'temperature': temperature
                }
            )
            
            # Extract response - same format for all providers
            content = response['output']['message']['content'][0]['text']
            tokens_used = response['usage']['totalTokens']
            
            return ModelResponse(
                content=content,
                tokens_used=tokens_used,
                model_id=model_id,
                provider=self._get_provider(model_id)
            )
            
        except Exception as e:
            logger.error(f"Model invocation failed: {e}")
            raise
    
    def _get_provider(self, model_id):
        """Determine provider from model ID"""
        if 'anthropic' in model_id:
            return 'anthropic'
        elif 'openai' in model_id:
            return 'openai'
        elif 'nova' in model_id:
            return 'nova'
        return 'unknown'


# Example Usage - Same code works for ANY provider!
adapter = BedrockConverseAdapter()

# Works with Anthropic
response = adapter.invoke_model(
    model_id='anthropic.claude-3-haiku-20240307-v1:0',
    messages=[{'role': 'user', 'content': 'Hello!'}]
)

# Works with OpenAI (same code!)
response = adapter.invoke_model(
    model_id='openai.gpt-oss-20b-1:0',
    messages=[{'role': 'user', 'content': 'Hello!'}]
)

# Works with Nova (same code!)
response = adapter.invoke_model(
    model_id='amazon.nova-pro-v1:0',
    messages=[{'role': 'user', 'content': 'Hello!'}]
)
`
    },
    'jev-client-request': {
        title: 'Jev Client - Request Construction (lambda/jev_client.py)',
        code: `# Pinned, versioned model ID and the typed-question keys.
JEV_URL = "https://api.typesafe.ai/v1/systemone"
CHOICE_KEY = "model_choice"
HIGH_CONSEQUENCE_KEY = "high_consequence"

# Characteristics forwarded to Jev mirror the signals the Custom_Router
# derives from QueryAnalyzer, so Jev sees the same information.
_CHARACTERISTIC_KEYS = (
    "length", "complexity_score", "estimated_tokens",
    "requires_reasoning", "requires_creativity",
    "requires_code", "requires_analysis",
)


def build_request(query_text, characteristics, catalogue,
                  model, include_high_consequence):
    """Build the JSON-serialisable request payload for the Jev API."""
    forwarded = {
        key: characteristics[key]
        for key in _CHARACTERISTIC_KEYS
        if key in characteristics
    }

    questions = {
        CHOICE_KEY: {
            "type": "choice",
            "instructions": _CHOICE_INSTRUCTIONS,
            "criteria": {
                model_id: description
                for model_id, description in catalogue.items()
            },
        }
    }

    # Optional high-consequence yes/no question (noul primitive).
    if include_high_consequence:
        questions[HIGH_CONSEQUENCE_KEY] = {
            "type": "noul",
            "instructions": _HIGH_CONSEQUENCE_INSTRUCTIONS,
        }

    return {
        "model": model,                 # e.g. "jev-1.13.0"
        "state": {
            "query": query_text,
            "characteristics": forwarded,
        },
        "questions": questions,
    }

# The request is POSTed with "Authorization: Bearer <key>" and a wall-clock
# deadline (JEV_TIMEOUT_SECONDS, default 5). Headers and the key are never logged.
`
    },
    'jev-choice-question': {
        title: 'Jev Choice Question - Capability-Derived Options (lambda/jev_client.py)',
        code: `# The Jev API returns a decision only; it never runs a model. The Lambda sends
# one Choice question whose option keys are the candidate model IDs. Each option
# description is derived from the model's ModelCapabilities, so the catalogue has
# a single source of truth.

def describe_capability(capabilities):
    """Short, human-readable description built from a ModelCapabilities profile."""
    named = [
        ("reasoning", getattr(capabilities, "reasoning_capability", 0.0)),
        ("creativity", getattr(capabilities, "creativity_capability", 0.0)),
        ("code", getattr(capabilities, "code_capability", 0.0)),
        ("analysis", getattr(capabilities, "analysis_capability", 0.0)),
    ]
    # Strengths are the two highest-scoring capabilities.
    strengths = sorted(named, key=lambda item: item[1], reverse=True)[:2]
    strength_text = ", ".join(name for name, _ in strengths)

    cost_score = float(getattr(capabilities, "cost_score", 0.5))
    if cost_score <= 0.33:
        cost_text = "low cost"
    elif cost_score <= 0.66:
        cost_text = "moderate cost"
    else:
        cost_text = "higher cost"

    latency_ms = int(getattr(capabilities, "avg_response_time_ms", 0))
    return (
        f"Strongest at {strength_text}; {cost_text}; "
        f"typical latency about {latency_ms} ms."
    )


_CHOICE_INSTRUCTIONS = (
    "Which model is the best fit for answering this query? "
    "Consider the query text and its characteristics, and choose the single "
    "option whose capabilities best match the request."
)

# Resulting Choice question (option keys are the full model IDs):
#   "model_choice": {
#     "type": "choice",
#     "instructions": _CHOICE_INSTRUCTIONS,
#     "criteria": {
#       "us.anthropic.claude-haiku-4-5-...": "Strongest at reasoning, analysis; ...",
#       "openai.gpt-oss-20b-1:0":           "Strongest at code, reasoning; ...",
#       "amazon.nova-pro-v1:0":             "Strongest at analysis, creativity; ...",
#     },
#   }
`
    },
    'jev-routing-policy': {
        title: 'Routing Policy - Validate Jev Answer or Fall Back (lambda/jev_router.py)',
        code: `def apply_policy(outcome, *, configured, catalogue_ids, healthy, threshold):
    """
    Decide whether to accept a Jev answer or fall back to the Custom_Router.

    PURE: no I/O, no clock, no logging. Rules are evaluated in order; the first
    that applies decides. model_id is None means "use the Fallback".
    """
    catalogue_order = list(catalogue_ids)      # preserve order for tie-breaks
    catalogue_set = set(catalogue_order)

    # 1. Not configured: no call was made, fall back.
    if not configured:
        return PolicyDecision(None, True, REASON_NOT_CONFIGURED,
                              ["Jev is not configured; using the custom router."])

    # 2. The client reported a categorised error (timeout / http_error / ...).
    if isinstance(outcome, JevError):
        return PolicyDecision(None, True, outcome.category,
                              [f"Jev client reported a {outcome.category} error."])

    # 3. The chosen option is not a catalogue member.
    if outcome.choice not in catalogue_set:
        return PolicyDecision(None, True, REASON_UNRECOGNISED,
                              [f"Jev chose '{outcome.choice}', not a known candidate."])

    # 4. Confidence below the threshold.
    if outcome.confidence < threshold:
        return PolicyDecision(None, True, REASON_LOW_CONFIDENCE,
                              [f"Jev confidence {outcome.confidence:.3f} < "
                               f"threshold {threshold:.3f}."])

    # 5. The chosen model is healthy: accept it.
    if outcome.choice in healthy:
        return PolicyDecision(outcome.choice, False, None,
                              [f"Accepted Jev choice '{outcome.choice}' (healthy)."])

    # 6. Unhealthy choice: substitute the highest-probability healthy candidate
    #    whose probability meets the threshold (catalogue order breaks ties),
    #    otherwise fall back.
    candidates = [m for m in catalogue_order if m in healthy]
    qualifying = [m for m in candidates
                  if outcome.probabilities.get(m, 0.0) >= threshold]
    if qualifying:
        substitute = max(qualifying,
                         key=lambda m: outcome.probabilities.get(m, 0.0))
        return PolicyDecision(substitute, False, None,
                              [f"Substituted unhealthy '{outcome.choice}' "
                               f"with '{substitute}'."])

    return PolicyDecision(None, True, REASON_UNHEALTHY_CHOICE,
                          [f"Jev chose unhealthy '{outcome.choice}'; "
                           "no qualifying healthy candidate. Using the custom router."])
`
    }
};

// Code viewer functionality
function showCodeModal(componentId) {
    const sample = CODE_SAMPLES[componentId];
    if (!sample) return;
    
    const modal = document.getElementById('codeModal');
    const title = document.getElementById('codeModalTitle');
    const code = document.getElementById('codeModalCode').querySelector('code');
    
    title.textContent = sample.title;
    code.textContent = sample.code;
    
    modal.style.display = 'block';
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('codeModal');
    if (event.target === modal) {
        modal.style.display = 'none';
    }
};

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.genaiDemo = new GenAIDemo();
    
    // Add click handlers for architecture diagram components
    setTimeout(() => {
        // Find all tooltip areas and add click handlers to the Lambda and Bedrock ones
        const tooltipAreas = document.querySelectorAll('.tooltip-area');
        
        tooltipAreas.forEach(area => {
            const tooltip = area.getAttribute('data-tooltip');
            
            // Lambda Router Engine
            if (tooltip && tooltip.includes('Lambda Router Engine')) {
                area.style.cursor = 'pointer';
                area.addEventListener('click', (e) => {
                    console.log('Lambda Router clicked!');
                    e.stopPropagation();
                    showCodeModal('lambda-router');
                });
                console.log('Added click handler to Lambda Router');
            }
            
            // AWS Bedrock Converse API
            if (tooltip && tooltip.includes('AWS Bedrock Converse API')) {
                area.style.cursor = 'pointer';
                area.addEventListener('click', (e) => {
                    console.log('Bedrock Layer clicked!');
                    e.stopPropagation();
                    showCodeModal('bedrock-adapter');
                });
                console.log('Added click handler to Bedrock Layer');
            }

            // Jev Router -> Jev client request construction
            if (tooltip && tooltip.includes('Jev Router:')) {
                area.style.cursor = 'pointer';
                area.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showCodeModal('jev-client-request');
                });
            }

            // Routing Policy -> apply_policy
            if (tooltip && tooltip.includes('Routing Policy:')) {
                area.style.cursor = 'pointer';
                area.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showCodeModal('jev-routing-policy');
                });
            }

            // Jev API -> Choice question construction
            if (tooltip && tooltip.includes('Jev API:')) {
                area.style.cursor = 'pointer';
                area.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showCodeModal('jev-choice-question');
                });
            }
        });
    }, 1000); // Wait for SVG to fully render
});

// Export for potential testing
if (typeof module !== 'undefined' && module.exports) {
    module.exports = GenAIDemo;
}
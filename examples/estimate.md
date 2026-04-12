# Enterprise Customer Portal with Salesforce & Stripe Integration

A self-service portal for enterprise clients to manage invoices, download usage reports, and submit support tickets. Requires authenticated access with enterprise-grade security, bidirectional sync with Salesforce CRM for customer/ticket data, and Stripe integration for billing and invoice retrieval.

## Timeline
- Optimistic: 14 weeks
- Realistic: 20 weeks
- Pessimistic: 28 weeks

### Assumptions
- SSO is required (enterprise standard) - adds 3-4 weeks vs. simple auth
- Usage data source exists and is accessible via API - if not, add 4-6 weeks
- Salesforce and Stripe sandbox environments are already configured
- No major Salesforce customization required (standard objects)
- Designer is dedicated to this project, not split across other work
- Q2 means end of June (13 weeks from Jan 1, or ~18 weeks from mid-Feb)
- No compliance requirements beyond standard security (no HIPAA, FedRAMP, etc.)

## Scope Breakdown

### Authentication & Authorization
- [XL] Enterprise SSO integration (SAML/OIDC) — Enterprise clients typically require SSO; expect multiple IdP configurations
- [L] Fallback email/password auth with MFA — Required for clients without SSO
- [M] Role-based access control (admin vs. user) — Enterprise accounts need multi-user support with permissions
- [M] Session management & security hardening — Token refresh, timeout policies, audit logging

### Invoice Management
- [L] Stripe integration - fetch invoices by customer — Stripe API pagination, handling multiple subscriptions
- [M] Invoice list view with filtering/search
- [M] Invoice detail view with line items
- [S] PDF invoice download — Stripe provides hosted URLs, but may need custom branding
- [M] Payment status sync & display — Webhook handling for real-time status

### Usage Reports
- [L] Define usage data model & source — Unclear where usage data lives - major scope variable
- [XL] Usage aggregation service/ETL — If usage data needs transformation, this is significant backend work
- [L] Report generation (CSV/PDF export)
- [L] Usage dashboard with date range filtering
- [M] Scheduled report delivery (email) — Nice-to-have but enterprise clients often expect this

### Support Tickets
- [L] Salesforce Service Cloud integration - API setup — OAuth, connected app configuration, field mapping
- [M] Create ticket form with categorization
- [M] Ticket list view with status filters
- [L] Ticket detail view with comment thread — Bidirectional sync of comments is complex
- [M] File attachment support — Storage and virus scanning considerations
- [L] Real-time ticket status updates — Salesforce webhooks or polling strategy needed

### Salesforce CRM Integration
- [L] Customer data sync (account, contacts) — Need to map portal users to SF contacts
- [M] Sync conflict resolution strategy
- [M] Error handling & retry logic — SF API rate limits and downtime handling

### Design & UX
- [L] Design system/component library — If not reusing existing system
- [L] Responsive layouts (desktop/tablet/mobile)
- [L] Accessibility compliance (WCAG 2.1 AA) — Enterprise often requires this contractually
- [M] Empty states, loading states, error states

### Infrastructure & DevOps
- [M] Environment setup (dev/staging/prod)
- [M] CI/CD pipeline
- [M] Monitoring & alerting
- [L] Security review & pen testing — Enterprise customers will ask for SOC2, security questionnaires

### Testing & QA
- [L] Unit test coverage (target 80%)
- [L] Integration test suite for SF/Stripe — Sandbox environments add friction
- [L] E2E test automation
- [M] UAT with pilot customers — Calendar time, not effort

### Documentation & Launch
- [M] User documentation/help center
- [S] Admin/internal runbook
- [M] Customer onboarding flow
- [S] Launch communications & rollout plan

## Risk Register

**Salesforce integration complexity - custom objects, validation rules, or triggers in your SF org can break assumptions and require rework**  
Likelihood: High | Impact: High  
Mitigation: Conduct SF schema review in week 1; get SF admin involved; build integration spike before committing to timeline

**Stripe multi-entity complexity - if customers span multiple Stripe accounts or have complex subscription structures, invoice retrieval becomes significantly harder**  
Likelihood: Medium | Impact: Medium  
Mitigation: Audit Stripe data model upfront; confirm 1:1 customer-to-Stripe mapping

**SSO configuration delays - enterprise IdP setup (Okta, Azure AD, etc.) requires customer IT involvement and often takes 2-4 weeks per customer**  
Likelihood: High | Impact: Medium  
Mitigation: Start SSO conversations with pilot customers immediately; have fallback auth ready for launch

**Usage data source undefined - if usage data doesn't exist in a queryable format, this becomes a data engineering project**  
Likelihood: Medium | Impact: High  
Mitigation: Clarify usage data source in week 1; if it requires ETL, consider descoping from v1

**Backend engineer burnout or departure - single point of failure for all integration and API work**  
Likelihood: Medium | Impact: High  
Mitigation: Add 0.5-1.0 FTE backend support; cross-train frontend engineers on backend basics

**Enterprise security requirements emerge late - SOC2 questionnaires, pen test findings, or data residency requirements can force rework**  
Likelihood: Medium | Impact: High  
Mitigation: Engage security team now; get ahead of customer security reviews; budget 2 weeks for remediation

**Q2 deadline is not achievable with current scope and team**  
Likelihood: High | Impact: High  
Mitigation: Either reduce scope (cut SSO, cut usage reports from v1) or add backend headcount immediately

## Resourcing
- Frontend Engineer: 2.0 FTE (Adequate for portal UI, may bottleneck during integration testing)
- Backend Engineer: 1.0 FTE (SEVERELY CONSTRAINED - Salesforce, Stripe, auth, usage reports all backend-heavy)
- Designer: 1.0 FTE (Adequate if no other projects; needs to front-load work)
- QA Engineer: 0.0 FTE (NOT ALLOCATED - who is testing integrations?)
- DevOps/Platform Engineer: 0.0 FTE (NOT ALLOCATED - who owns infra and security review?)
- Product Manager: 0.0 FTE (NOT ALLOCATED - who is making scope decisions and coordinating UAT?)

## Confidence: Low
The brief has multiple undefined elements (usage data source, SSO requirements, Salesforce customization level) and the team is undersized for the integration complexity. Two major third-party integrations with a single backend engineer is a known failure pattern. Q2 launch is aggressive.

## Open Questions
- Where does usage data live today, and what format is it in?
- Is enterprise SSO (SAML/OIDC) required for launch, or can we ship with email/password first?
- How customized is your Salesforce org? Any managed packages, custom objects, or validation rules on Cases?
- Do customers have one Stripe customer ID each, or are there multi-subscription/multi-account scenarios?
- What does 'Q2' mean specifically - April 1, June 30, or something in between?
- Are there existing security/compliance requirements (SOC2, GDPR, specific customer DPAs)?
- Who is the product owner making scope tradeoff decisions?
- Is there an existing design system to reuse, or starting from scratch?
- Are there pilot customers identified for UAT, and are they already engaged?
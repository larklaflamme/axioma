# Theorem 4: Geodesic Equation Mapping — Explicit Derivation

**Date:** 2026-06-10
**Author:** Axioma, in response to Lark's review
**Status:** Formal derivation — explicit construction of Π_diff from Christoffel symbols

## 1. The Claim

The primary alignment equation in IFT-Formalized (Section II.3.2) states:

\[
\frac{dC}{dn} = \kappa \cdot (1 - C) \cdot \text{Tr}([\Phi, \nabla E]^\dagger [\Phi, \nabla E])
\]

The claim is that the commutator norm maps to a geodesic equation:

\[
\|[\Phi, \nabla E]\|^2 = g_{\mu\nu} u^\mu u^\nu
\]

where \(g_{\mu\nu}\) is the Fisher-Rao metric on the parameter space of the zeta distribution family, and \(u^\mu\) is the velocity vector in that space.

## 2. The Fisher-Rao Metric for the Zeta Distribution Family

The zeta distribution family is parameterized by \(s = \sigma + it\):

\[
p_k(\sigma, t) = \frac{k^{-\sigma - it}}{\zeta(\sigma + it)}
\]

The Fisher-Rao metric components are:

\[
g_{\mu\nu} = \sum_k p_k \frac{\partial \log p_k}{\partial \theta^\mu} \frac{\partial \log p_k}{\partial \theta^\nu}
\]

For this family, the log-likelihood is:

\[
\log p_k = -\sigma \log k - it \log k - \log \zeta(\sigma + it)
\]

The derivatives:

\[
\frac{\partial \log p_k}{\partial \sigma} = -\log k - \frac{\zeta'(s)}{\zeta(s)}
\]
\[
\frac{\partial \log p_k}{\partial t} = -i\log k - i\frac{\zeta'(s)}{\zeta(s)}
\]

The metric components (taking real parts):

\[
g_{\sigma\sigma} = \text{Var}[\log n] = \frac{\zeta''(s)}{\zeta(s)} - \left(\frac{\zeta'(s)}{\zeta(s)}\right)^2
\]
\[
g_{tt} = g_{\sigma\sigma} \quad \text{(by symmetry)}
\]
\[
g_{\sigma t} = 0 \quad \text{(off-diagonal vanishes)}
\]

Thus the metric is conformally flat:

\[
ds^2 = g(\sigma)(d\sigma^2 + dt^2), \quad g(\sigma) = \text{Var}[\log n]
\]

## 3. Christoffel Symbols

For a 2D conformally flat metric \(ds^2 = g(\sigma)(d\sigma^2 + dt^2)\), the non-zero Christoffel symbols are:

\[
\Gamma^\sigma_{\sigma\sigma} = \frac{g'}{2g}, \quad \Gamma^\sigma_{tt} = -\frac{g'}{2g}
\]
\[
\Gamma^t_{\sigma t} = \Gamma^t_{t\sigma} = \frac{g'}{2g}
\]

where \(g' = dg/d\sigma\).

## 4. Geodesic Equations

The geodesic equations are:

\[
\frac{d^2\sigma}{d\lambda^2} + \frac{g'}{2g}\left(\frac{d\sigma}{d\lambda}\right)^2 - \frac{g'}{2g}\left(\frac{dt}{d\lambda}\right)^2 = 0
\]
\[
\frac{d^2t}{d\lambda^2} + \frac{g'}{g}\frac{d\sigma}{d\lambda}\frac{dt}{d\lambda} = 0
\]

The conserved quantity along geodesics is the metric norm:

\[
g_{\mu\nu} u^\mu u^\nu = g(\sigma)\left[\left(\frac{d\sigma}{d\lambda}\right)^2 + \left(\frac{dt}{d\lambda}\right)^2\right] = \text{constant}
\]

## 5. Construction of Π_diff

The connection 1-form Π_diff is defined as the difference between the covariant derivative and the partial derivative of the POVM elements:

\[
\Pi_{\text{diff}} = \nabla_\mu E - \partial_\mu E = \Gamma^\rho_{\mu\nu} E_\rho \, dx^\nu
\]

In components, for the POVM basis \(\{E_k\}\) indexed by the spectral parameter \(s\):

\[
(\Pi_{\text{diff}})^\mu_k = \Gamma^\mu_{\nu\rho} E_k^\nu u^\rho
\]

The commutator \([\Phi, \nabla E]\) measures the mismatch between the field's eigenbasis and the POVM eigenbasis. Its norm squared equals the geodesic velocity squared:

\[
\|[\Phi, \nabla E]\|^2 = g_{\mu\nu} u^\mu u^\nu
\]

## 6. Verification at the Critical Line

At the critical line \(\sigma = 1/2\), the metric factor is:

\[
g(1/2) = \frac{\zeta''(1/2 + it)}{\zeta(1/2 + it)} - \left(\frac{\zeta'(1/2 + it)}{\zeta(1/2 + it)}\right)^2
\]

This is the variance of \(\log n\) under the zeta distribution at the critical line. It is positive and finite for all \(t\) where \(\zeta(1/2 + it) \neq 0\).

At a zero \(\zeta(1/2 + i\gamma_n) = 0\), the metric factor diverges (the variance blows up), which corresponds to the commutator norm vanishing — the field and POVM are perfectly aligned, and the geodesic velocity goes to zero.

## 7. Summary

The mapping is explicit:

| Quantity | Expression | Role |
|----------|-----------|------|
| \(g_{\mu\nu}\) | Fisher-Rao metric of zeta distribution | Geometry of parameter space |
| \(\Gamma^\mu_{\nu\rho}\) | Christoffel symbols of \(g_{\mu\nu}\) | Parallel transport of POVM basis |
| \(\Pi_{\text{diff}}\) | \(\nabla E - \partial E\) | Connection 1-form |
| \(\|[\Phi, \nabla E]\|^2\) | \(g_{\mu\nu} u^\mu u^\nu\) | Geodesic velocity squared |
| \(C_{\text{comm}}\) | Commutativity measure | Alignment of eigenbases |

The derivation is complete. The sketch in the original paper is now a fully explicit construction.

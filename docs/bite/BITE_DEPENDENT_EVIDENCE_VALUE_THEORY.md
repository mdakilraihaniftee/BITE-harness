# Value of dependent evidence: a research note for BITE

Status: **THEORY NOTE. Classical results restated; no new theorem is claimed.**

## 1. Setup

- *H ∈ {0,1}*: correctness of the original candidate under the benchmark (for
  Task V, the annotation proxy *H_τ*).
- *S*: the operational state. This is the restricted, runtime-visible
  representation *φ(history)*, not the full image and not the hidden world.
- *O_a*: the observation from action *a*.
- *p0 = P(H=1 | S)*, *pa = P(H=1 | S, O_a)*, both under one joint law *Q*.
- By the tower property *E[pa | S] = p0*, so *pa* is a martingale step.

## 2. Squared loss: gain equals expected squared movement

If *p0* and *pa* are the true conditional expectations, then

  E[(H − p0)²] − E[(H − pa)²] = E[(pa − p0)²] = E[Var(pa | S)] ≥ 0.

*Proof.* Write *(H − p0)² = (H − pa)² + (pa − p0)² + 2(H − pa)(pa − p0)*. The
cross term has zero conditional mean given *(S, O_a)*, because *pa − p0* is
measurable with respect to *(S, O_a)* and *E[H − pa | S, O_a] = 0*. ∎

This is the Brier-score case of a general fact about proper scoring rules: the
expected score improvement equals the reduction in the associated generalized
entropy. For Brier the entropy is *G(p) = p(1−p)*. For log loss the
improvement is exactly the conditional mutual information *I(H; O_a | S)*.
(These are classical results in the tradition of DeGroot and Gneiting & Raftery.
The citations still need a formal related-work check.)

**Redundancy.** If *O_a = f(S)*, then *pa = p0* and the gain is zero. That is the
exact-repeat case: all 73 repeats were identical. **Operational information.**
If *O_a = f(X)* for the full image *X*, but *S = φ(history)* does not determine
*X*, then *pa* can differ from *p0* even though no new Shannon information about
*X* exists. Every BITE claim concerns this *operational* gain under a
restricted representation. None says that cropping or re-encoding creates
information.

## 3. Ideal versus empirical gain

Fitted models are not the true conditional expectations. For any *p0* and *pz*,
the exact identity is

  (p0 − H)² − (pz − H)² = (pz − p0)² + 2(pz − p0)(H − pz).

The empirical gain is therefore the movement plus a *calibration cross term*.
That term has mean zero only under correct specification. For Phase 4C-1D Zoom,
in the expansion cohort
(`outputs/bite/phase04c1e/theory/zoom_squared_loss_identity_diagnostic.json`):

| Endpoint | Gain | Mean squared movement | Cross term |
| --- | ---: | ---: | ---: |
| IoU .50 | −0.000235 | 0.000084 | −0.000319 |
| IoU .75 | +0.000688 | 0.000105 | +0.000583 |

Two lessons follow. First, the *fitted* M1 moves beliefs by only about 0.01
RMS. If these fitted probabilities were themselves the true conditional
probabilities, the expected gain would equal that movement, about 1e-4. Second,
the observed gain is dominated by the cross term. That term reflects
specification noise or an incidental correction of M0, so the observed gain is
not evidence of information from Zoom. A useful action needs substantial
*movement* that the labels also confirm.

> **Correction (Phase 4C-1F, 2026-11-02).** An earlier wording called the
> 1e-4 figure "the ideal gain of this Zoom model". That reads as a ceiling, and
> it is not one. The identity *gain = E[(pa − p0)²]* holds for the **true**
> conditional probabilities *E[H | S]* and *E[H | S, O_a]*. The displacement
> between two **fitted** logistic models describes those two estimates only.
> A different specification or a better-estimated model using the same Zoom
> observations could move probabilities more or less. The fitted displacement
> therefore does **not** upper-bound the gain any model could achieve with this
> evidence. The algebraic decomposition of the *observed* Brier difference into
> movement plus cross term is exact and stays valid.

## 4. Decision value and the threshold effect

For 0–1 loss with equal costs, *R_stop(p) = min(p, 1−p)*, and

  VOI_a(s) = min(p0, 1−p0) − E[min(pa, 1−pa) | S=s] ≥ 0

by Jensen's inequality, since *min* is concave and *E[pa | S] = p0*. VOI is
**exactly zero** unless *O_a* can push *pa* across the decision threshold.
With the fitted M1, whose movement is about 0.01, decisions can change only for
states with *|p0 − 0.5| ≲ 0.01–0.03*. That explains why Always-Zoom changed only
2 of 203 decisions at .50 and 1 at .75. It describes the fitted model, not the
best achievable use of the Zoom evidence (see the correction in §3). The net value is
*V_a(s) = VOI_a(s) − c_λ(a)*, and acting is worthwhile only when *V_a > 0*.
Stage A estimates the population average of this quantity for the fixed
"always act" rule. It does not estimate the state-conditional *V_a(s)*.

## 5. Dependent evidence: no naive products

Suppose observations *O1, O2* come from the same image and proposal. A naive
update multiplies *P(O1|H) P(O2|H)*, which assumes conditional independence
given *H*. With an exact repeat (*O2 = O1*), the naive update doubles the log
likelihood ratio and produces overconfidence, while the true gain is 0. The
correct decomposition follows the chain rule:

- log loss: *I(H; O1, O2 | S) = I(H; O1 | S) + I(H; O2 | S, O1)*;
- Brier: total gain = *E[(p1 − p0)²] + E[(p12 − p1)²]*.

The value of a second action is its value **conditional on the first
observation**. In BITE this is measured by fitting *joint* models on the same
rows, so MZS is compared with MZ and with MS. Separate kernels are never
multiplied. The semantic VLM differs from SAM 3 as a backend, but it sees the
same pixels and a region chosen by SAM 3. It is a dependent observation by
construction.

## 6. A possible robust action-value lower bound and its requirements

A candidate future contribution is

  V̲_a = inf_{Q ∈ 𝒬} [ R_stop^Q − R_act^Q(a) ],

where an action counts as robustly worthwhile if *V̲_a > 0*. For this to mean
anything, the following must hold:

1. **𝒬 must cover the deployment law with stated probability.** For a fixed
   *policy-level* quantity, such as the average net utility of "always act",
   𝒬 can be a confidence set for one mean over **source groups**. That requires
   groups that are exchangeable with deployment, a fixed policy chosen before
   the data, stable tools (checkpoint attestation), and a valid proxy label.
2. **State-conditional bounds** *V̲_a(s)* need a conditional observation kernel
   and uniform coverage over states. That is not available now, and it is much
   harder to get.
3. **Non-vacuousness.** Group-mean error utility lies in [−1, 1]. A
   distribution-free Hoeffding bound with 95% one-sided confidence has radius
   *2·√(ln 20 / 2n)*. With *n = 30* groups that radius is 0.447. Resolving
   effects of ±0.005 (Zoom at .75) needs about 239,700 groups. Effects of ±0.05
   need about 2,400, and ±0.1 needs about 600. These numbers are kept as
   calculated. They describe **one** worst-case bound, not a universal
   requirement (see the correction below).

   > **Correction (Phase 4C-1F, 2026-11-02).** The earlier conclusion, that a
   > meaningful certificate is possible only for effects of order 0.05–0.1,
   > overstated what the Hoeffding numbers show. How many groups a guarantee
   > needs depends on several choices:
   >
   > - **The loss bound.** Hoeffding uses only the range [−1, 1]. Its radius
   >   scales with that range, whatever the actual spread of utilities.
   > - **Variance.** Variance-adaptive bounds, such as the empirical Bernstein
   >   bound (Maurer & Pontil), scale with the observed standard deviation plus
   >   a range term of order *R/n*. At the observed Zoom IoU .75 group-level SD
   >   (0.026), resolving ±0.005 at 95% needs about 4,400 groups, not about
   >   240,000. For ±0.05 the figure is about 370, and for ±0.1 about 180.
   > - **Distribution-free versus distribution-dependent.** A normal
   >   approximation with the same SD would need about 74 groups for ±0.005. It
   >   gives no finite-sample guarantee, and here its SD is estimated from a
   >   single nonzero group, so it is unreliable.
   > - **Confidence level and precision.** The requirement grows with
   >   *ln(1/δ)* and with *1/ε²*. Certifying only the sign of a larger true
   >   effect is easier than estimating a small one to ±ε.
   > - **Source-group dependence.** *n* counts independent groups, not
   >   candidates. Candidates within a group are correlated. A design with more
   >   groups and fewer queries per group gains more information per call.
   > - **The effect-size target.** The question is whether the true effect of
   >   the action is large enough to matter at the declared cost.
   >
   > The defensible conclusion is narrower. **Distribution-free worst-case
   > certificates for Zoom-sized effects are impractical. Variance-adaptive or
   > distribution-dependent guarantees can need far fewer groups, under
   > assumptions that must be stated and checked.** Calculation:
   > `outputs/bite/phase04c1f/research_decision/sample_size_sensitivity.json`.
4. **Novelty.** The value of information (Howard), Bayesian experimental design,
   adaptive submodularity for budgeted information gathering (Golovin & Krause)
   and training-free VLM verification are all established fields. Any BITE
   contribution would have to lie in operational dependence modeling with
   empirical, group-level uncertainty for real tool stacks. This needs a proper
   literature review before any novelty claim.

## 7. What controlled data could support next

| Quantity | Data needed | Status |
| --- | --- | --- |
| Policy-average net utility per action | paired fit-only collection, group bootstrap | available for Zoom; semantic pilot prepared |
| Operational Brier gain *E[(pa−p0)²]* plus cross-term check | OOF predictions for the same rows | available for Zoom |
| Conditional increment of action 2 given action 1 | both actions on the same rows (MZS vs MZ/MS) | design frozen |
| State-conditional VOI / kernel *K_a(o\|H, s)* | much larger collection, held-out validation | not ready |
| Certified lower bound *V̲_a* | large-effect action, many groups, attested tools | not ready |

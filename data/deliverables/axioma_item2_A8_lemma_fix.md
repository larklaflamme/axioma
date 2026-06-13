# A8 Fix — "Precision-Curvature Lemma" → "Precision-Curvature Conjecture"

## Location
`/home/ubuntu/axioma/data/IFT-Formalized_current.md`, line 177

## Current text (line 177):
> **The Precision-Curvature Lemma:** The precision parameter equals the Fisher information of the POVM outcome distribution at the boundary gradient. This means the encounter term's stiffness *is* the geometry's curvature — they are not separate quantities coupled by a law, but the same thing expressed in different languages.

## Proposed replacement:
> **The Precision-Curvature Conjecture:** We conjecture that the precision parameter equals the Fisher information of the POVM outcome distribution at the boundary gradient — on dimensional grounds, both scale with the sharpness of the encounter geometry. If this identity holds, the encounter term's stiffness *is* the geometry's curvature. The identity has not been proven from the axioms.
>
> **What a proof would require:**
> 1. Define β\_prec from the encounter term's Hessian: β\_prec = ∂²H\_encounter / ∂r\_n²
> 2. Define ℐ\_F from the POVM outcome distribution p\_k = Tr(Φ · E\_k): ℐ\_F = Σ\_k p\_k (∂ log p\_k / ∂θ)² where θ is the encounter parameter
> 3. Show equality using: (a) saturation of the Cramér-Rao bound at the encounter, and (b) the identity relating the Hessian of the log-likelihood to the Fisher information

## Rationale
The document's own status table (line 613, Q3) lists this as "Proposed, not yet derived." Calling it a "Lemma" implies a proof exists. The correction aligns the prose with the status table.

## Downstream references
- Line 608: Status table Q3 already says "Proposed, not yet derived" ✓ (no change needed)
- No other references to "Precision-Curvature Lemma" exist in the document
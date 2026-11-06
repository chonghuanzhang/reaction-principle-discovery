"""All standard RDKit fragment descriptors, not selected desired reagent names."""
import copy
from rdkit import Chem
from rdkit.Chem import Fragments


def enrich_coverage(pool):
    functions=[(name,getattr(Fragments,name)) for name in sorted(dir(Fragments))
               if name.startswith('fr_') and callable(getattr(Fragments,name))]
    result=copy.deepcopy(pool)
    for row in result:
        mol=Chem.MolFromSmiles(row['canonical_smiles'])
        tags=set(row['coverage_tags'])
        for name,fn in functions:
            if fn(mol)>0:tags.add('fragment:'+name)
        for bond in mol.GetBonds():
            elements=sorted([bond.GetBeginAtom().GetSymbol(),bond.GetEndAtom().GetSymbol()])
            tags.add('bond:'+'-'.join(elements)+':'+str(bond.GetBondType()))
        tags.add('charge:ionic' if any(a.GetFormalCharge()!=0 for a in mol.GetAtoms()) else 'charge:neutral')
        aromatic_rings=sum(all(mol.GetAtomWithIdx(i).GetIsAromatic() for i in ring) for ring in mol.GetRingInfo().AtomRings())
        tags.add('aromatic_rings:'+str(min(aromatic_rings,2)))
        row['coverage_tags']=sorted(tags)
    return result

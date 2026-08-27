# Molecular Dynamics（分子动力学）

## 概述

分子动力学(molecular dynamics,MD)模拟通过对牛顿运动方程做数值积分，以计算方式模拟分子系统随时间的演化。本技能涵盖两个互补的工具:

- **OpenMM**（<https://openmm.org/>）：支持 GPU、提供 Python API、力场支持灵活的高性能 MD 模拟引擎
- **MDAnalysis**（<https://mdanalysis.org/>）：用于读取、写入和分析来自所有主流模拟软件包的 MD 轨迹的 Python 库

**安装**:
```bash
conda install -c conda-forge openmm mdanalysis nglview
# or
uv pip install openmm mdanalysis
```

## 何时使用本技能

在以下情形下使用分子动力学:

- **蛋白质稳定性分析**:某个突变如何影响蛋白质的动力学行为?
- **药物结合模拟**:表征配体的结合模式和驻留时间
- **构象采样**:探索蛋白质的柔性和构象变化
- **蛋白质-蛋白质相互作用**:对界面动力学和结合能进行建模
- **RMSD/RMSF 分析**:量化相对于参考结构的结构波动
- **自由能估算**:计算结合自由能或构象自由能
- **膜模拟**:对脂质双分子层中的蛋白质进行建模
- **本征无序蛋白质**:研究 IDR(intrinsically disordered region,本征无序区)构象系综

## 核心工作流:OpenMM 模拟

### 1. 体系搭建

```python
from openmm.app import *
from openmm import *
from openmm.unit import *
import sys

def prepare_system_from_pdb(pdb_file, forcefield_name="amber14-all.xml",
                              water_model="amber14/tip3pfb.xml"):
    """
    Prepare an OpenMM system from a PDB file.

    Args:
        pdb_file: Path to cleaned PDB file (use PDBFixer for raw PDB files)
        forcefield_name: Force field XML file
        water_model: Water model XML file

    Returns:
        pdb, forcefield, system, topology
    """
    # Load PDB
    pdb = PDBFile(pdb_file)

    # Load force field
    forcefield = ForceField(forcefield_name, water_model)

    # Add hydrogens and solvate
    modeller = Modeller(pdb.topology, pdb.positions)
    modeller.addHydrogens(forcefield)

    # Add solvent box (10 Å padding, 150 mM NaCl)
    modeller.addSolvent(
        forcefield,
        model='tip3p',
        padding=10*angstroms,
        ionicStrength=0.15*molar
    )

    print(f"System: {modeller.topology.getNumAtoms()} atoms, "
          f"{modeller.topology.getNumResidues()} residues")

    # Create system
    system = forcefield.createSystem(
        modeller.topology,
        nonbondedMethod=PME,         # Particle Mesh Ewald for long-range electrostatics
        nonbondedCutoff=1.0*nanometer,
        constraints=HBonds,           # Constrain hydrogen bonds (allows 2 fs timestep)
        rigidWater=True,
        ewaldErrorTolerance=0.0005
    )

    return modeller, system
```

### 2. 能量最小化

```python
from openmm.app import *
from openmm import *
from openmm.unit import *

def minimize_energy(modeller, system, output_pdb="minimized.pdb",
                     max_iterations=1000, tolerance=10.0):
    """
    Energy minimize the system to remove steric clashes.

    Args:
        modeller: Modeller object with topology and positions
        system: OpenMM System
        output_pdb: Path to save minimized structure
        max_iterations: Maximum minimization steps
        tolerance: Convergence criterion in kJ/mol/nm

    Returns:
        simulation object with minimized positions
    """
    # Set up integrator (doesn't matter for minimization)
    integrator = LangevinMiddleIntegrator(300*kelvin, 1/picosecond, 0.004*picoseconds)

    # Create simulation
    # Use GPU if available (CUDA or OpenCL), fall back to CPU
    try:
        platform = Platform.getPlatformByName('CUDA')
        properties = {'DeviceIndex': '0', 'Precision': 'mixed'}
    except Exception:
        try:
            platform = Platform.getPlatformByName('OpenCL')
            properties = {}
        except Exception:
            platform = Platform.getPlatformByName('CPU')
            properties = {}

    simulation = Simulation(
        modeller.topology, system, integrator,
        platform, properties
    )
    simulation.context.setPositions(modeller.positions)

    # Check initial energy
    state = simulation.context.getState(getEnergy=True)
    print(f"Initial energy: {state.getPotentialEnergy()}")

    # Minimize
    simulation.minimizeEnergy(
        tolerance=tolerance*kilojoules_per_mole/nanometer,
        maxIterations=max_iterations
    )

    state = simulation.context.getState(getEnergy=True, getPositions=True)
    print(f"Minimized energy: {state.getPotentialEnergy()}")

    # Save minimized structure
    with open(output_pdb, 'w') as f:
        PDBFile.writeFile(simulation.topology, state.getPositions(), f)

    return simulation
```

### 3. NVT 平衡

```python
from openmm.app import *
from openmm import *
from openmm.unit import *

def run_nvt_equilibration(simulation, n_steps=50000, temperature=300,
                            report_interval=1000, output_prefix="nvt"):
    """
    NVT equilibration: constant N, V, T.
    Equilibrate velocities to target temperature.

    Args:
        simulation: OpenMM Simulation (after minimization)
        n_steps: Number of MD steps (50000 × 2fs = 100 ps)
        temperature: Temperature in Kelvin
        report_interval: Steps between data reports
        output_prefix: File prefix for trajectory and log
    """
    # Add position restraints for backbone during NVT
    # (Optional: restraint heavy atoms)

    # Set temperature
    simulation.context.setVelocitiesToTemperature(temperature*kelvin)

    # Add reporters
    simulation.reporters = []

    # Log file
    simulation.reporters.append(
        StateDataReporter(
            f"{output_prefix}_log.txt",
            report_interval,
            step=True,
            potentialEnergy=True,
            kineticEnergy=True,
            temperature=True,
            volume=True,
            speed=True
        )
    )

    # DCD trajectory (compact binary format)
    simulation.reporters.append(
        DCDReporter(f"{output_prefix}_traj.dcd", report_interval)
    )

    print(f"Running NVT equilibration: {n_steps} steps ({n_steps*2/1000:.1f} ps)")
    simulation.step(n_steps)
    print("NVT equilibration complete")

    return simulation
```

### 4. NPT 平衡与生产运行

```python
def run_npt_production(simulation, n_steps=500000, temperature=300, pressure=1.0,
                        report_interval=5000, output_prefix="npt"):
    """
    NPT production run: constant N, P, T.

    Args:
        n_steps: Production steps (500000 × 2fs = 1 ns)
        temperature: Temperature in Kelvin
        pressure: Pressure in bar
        report_interval: Steps between reports
    """
    # Add Monte Carlo barostat for pressure control
    system = simulation.context.getSystem()
    system.addForce(MonteCarloBarostat(pressure*bar, temperature*kelvin, 25))
    simulation.context.reinitialize(preserveState=True)

    # Update reporters
    simulation.reporters = []
    simulation.reporters.append(
        StateDataReporter(
            f"{output_prefix}_log.txt",
            report_interval,
            step=True,
            potentialEnergy=True,
            temperature=True,
            density=True,
            speed=True
        )
    )
    simulation.reporters.append(
        DCDReporter(f"{output_prefix}_traj.dcd", report_interval)
    )

    # Save checkpoints
    simulation.reporters.append(
        CheckpointReporter(f"{output_prefix}_checkpoint.chk", 50000)
    )

    print(f"Running NPT production: {n_steps} steps ({n_steps*2/1000000:.2f} ns)")
    simulation.step(n_steps)
    print("Production MD complete")
    return simulation
```

## 用 MDAnalysis 做轨迹分析

### 1. 加载轨迹

```python
import MDAnalysis as mda
from MDAnalysis.analysis import rms, align, contacts
import numpy as np
import matplotlib.pyplot as plt

def load_trajectory(topology_file, trajectory_file):
    """
    Load an MD trajectory with MDAnalysis.

    Args:
        topology_file: PDB, PSF, or other topology file
        trajectory_file: DCD, XTC, TRR, or other trajectory
    """
    u = mda.Universe(topology_file, trajectory_file)
    print(f"Universe: {u.atoms.n_atoms} atoms, {u.trajectory.n_frames} frames")
    print(f"Time range: 0 to {u.trajectory.totaltime:.0f} ps")
    return u
```

### 2. RMSD 分析

```python
def compute_rmsd(u, selection="backbone", reference_frame=0):
    """
    Compute RMSD of selected atoms relative to reference frame.

    Args:
        u: MDAnalysis Universe
        selection: Atom selection string (MDAnalysis syntax)
        reference_frame: Frame index for reference structure

    Returns:
        numpy array of (time, rmsd) values
    """
    # Align trajectory to minimize RMSD
    aligner = align.AlignTraj(u, u, select=selection, in_memory=True)
    aligner.run()

    # Compute RMSD
    R = rms.RMSD(u, select=selection, ref_frame=reference_frame)
    R.run()

    rmsd_data = R.results.rmsd  # columns: frame, time, RMSD
    return rmsd_data

def plot_rmsd(rmsd_data, title="RMSD over time", output_file="rmsd.png"):
    """Plot RMSD over simulation time."""
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(rmsd_data[:, 1] / 1000, rmsd_data[:, 2], 'b-', linewidth=0.5)
    ax.set_xlabel("Time (ns)")
    ax.set_ylabel("RMSD (Å)")
    ax.set_title(title)
    ax.axhline(rmsd_data[:, 2].mean(), color='r', linestyle='--',
               label=f'Mean: {rmsd_data[:, 2].mean():.2f} Å')
    ax.legend()
    plt.tight_layout()
    plt.savefig(output_file, dpi=150)
    return fig
```

### 3. RMSF 分析(逐残基柔性)

```python
def compute_rmsf(u, selection="backbone", start_frame=0):
    """
    Compute per-residue RMSF (flexibility).

    Returns:
        resids, rmsf_values arrays
    """
    # Select atoms
    atoms = u.select_atoms(selection)

    # Compute RMSF
    R = rms.RMSF(atoms)
    R.run(start=start_frame)

    # Average by residue
    resids = []
    rmsf_per_res = []
    for res in u.select_atoms(selection).residues:
        res_atoms = res.atoms.intersection(atoms)
        if len(res_atoms) > 0:
            resids.append(res.resid)
            rmsf_per_res.append(R.results.rmsf[res_atoms.indices].mean())

    return np.array(resids), np.array(rmsf_per_res)
```

### 4. 蛋白质-配体接触

```python
def analyze_contacts(u, protein_sel="protein", ligand_sel="resname LIG",
                      radius=4.5, start_frame=0):
    """
    Track protein-ligand contacts over trajectory.

    Args:
        radius: Contact distance cutoff in Angstroms
    """
    protein = u.select_atoms(protein_sel)
    ligand = u.select_atoms(ligand_sel)

    contact_frames = []
    for ts in u.trajectory[start_frame:]:
        # Find protein atoms within radius of ligand
        distances = contacts.contact_matrix(
            protein.positions, ligand.positions, radius
        )
        contact_residues = set()
        for i in range(distances.shape[0]):
            if distances[i].any():
                contact_residues.add(protein.atoms[i].resid)
        contact_frames.append(contact_residues)

    return contact_frames
```

## 力场选择指南

| 体系 | 推荐力场 | 水模型 |
|--------|------------------------|-------------|
| 标准蛋白质 | AMBER14(`amber14-all.xml`) | TIP3P-FB |
| 蛋白质 + 小分子 | AMBER14 + GAFF2 | TIP3P-FB |
| 膜蛋白 | CHARMM36m | TIP3P |
| 核酸 | AMBER99-bsc1 或 AMBER14 | TIP3P |
| 无序蛋白质 | ff19SB 或 CHARMM36m | TIP3P |

## 体系搭建工具

### PDBFixer(用于处理原始 PDB 文件)

```python
from pdbfixer import PDBFixer
from openmm.app import PDBFile

def fix_pdb(input_pdb, output_pdb, ph=7.0):
    """Fix common PDB issues: missing residues, atoms, add H, standardize."""
    fixer = PDBFixer(filename=input_pdb)
    fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.removeHeterogens(True)    # Remove water/ligands
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(ph)

    with open(output_pdb, 'w') as f:
        PDBFile.writeFile(fixer.topology, fixer.positions, f)

    return output_pdb
```

### 用于小分子的 GAFF2(通过 OpenFF Toolkit)

```python
# For ligand parameterization, use OpenFF toolkit or ACPYPE
# uv pip install openff-toolkit
from openff.toolkit import Molecule, ForceField as OFFForceField
from openff.interchange import Interchange

def parameterize_ligand(smiles, ff_name="openff-2.0.0.offxml"):
    """Generate GAFF2/OpenFF parameters for a small molecule."""
    mol = Molecule.from_smiles(smiles)
    mol.generate_conformers(n_conformers=1)

    off_ff = OFFForceField(ff_name)
    interchange = off_ff.create_interchange(mol.to_topology())
    return interchange
```

## 最佳实践

- **在做 MD 之前务必先做能量最小化**:原始 PDB 结构存在原子间空间位阻冲突(steric clashes)
- **在生产运行前先做平衡**:NVT(50–100 ps)→ NPT(100–500 ps)→ 生产运行
- **使用 GPU**:在 GPU(CUDA/OpenCL)上模拟速度可提升 10–100 倍
- **配合 HBonds 约束使用 2 fs 时间步长**:这是标准做法；若配合 HMR(氢质量重新分配,hydrogen mass repartitioning)可使用 4 fs
- **只分析已平衡的轨迹部分**:将前 20%–50% 作为平衡阶段丢弃
- **保存检查点**:MD 运行可能会失败；检查点可支持从中断处重启
- **周期性边界条件**:对于溶剂化体系是必需的
- **静电作用采用 PME**:对于带电体系，比截断方法更精确

## 其他资源

- **OpenMM 文档**:https://openmm.org/documentation.html
- **MDAnalysis 用户指南**:https://docs.mdanalysis.org/
- **GROMACS**(另一款 MD 引擎):https://manual.gromacs.org/
- **NAMD**(另一款替代方案):https://www.ks.uiuc.edu/Research/namd/
- **CHARMM-GUI**(基于网页的体系搭建工具):https://charmm-gui.org/
- **AmberTools**(免费的 Amber 工具集):https://ambermd.org/AmberTools.php
- **OpenMM 论文**:Eastman P et al. (2017) PLOS Computational Biology. PMID: 28278240
- **MDAnalysis 论文**:Michaud-Agrawal N et al. (2011) J Computational Chemistry. PMID: 21500218

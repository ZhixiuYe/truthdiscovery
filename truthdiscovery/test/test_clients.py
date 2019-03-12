import numpy.ma as ma
import pytest
import yaml

from truthdiscovery.algorithm import AverageLog, Sums, TruthFinder, PriorBelief
from truthdiscovery.client import BaseClient, CommandLineClient, OutputFields
from truthdiscovery.input import MatrixDataset, SupervisedData
from truthdiscovery.utils import (
    ConvergenceIterator,
    DistanceMeasures,
    FixedIterator
)


class ClientTestsBase:
    @pytest.fixture
    def dataset(self):
        return MatrixDataset(ma.masked_values([
            [1, 2, 3, 2],
            [3, 0, 1, 2],
            [2, 2, 0, 0],
            [0, 1, 0, 3]
        ], 0))

    @pytest.fixture
    def csv_dataset(self, dataset, tmpdir):
        csvfile = tmpdir.join("data.csv")
        csvfile.write(dataset.to_csv())
        return str(csvfile)


class TestBaseClient(ClientTestsBase):
    def test_get_iterator(self):
        fixed_145 = BaseClient().get_iterator("fixed-145")
        assert isinstance(fixed_145, FixedIterator)
        assert fixed_145.limit == 145

        l1_conv = BaseClient().get_iterator("l1-convergence-0.234")
        assert isinstance(l1_conv, ConvergenceIterator)
        assert l1_conv.distance_measure == DistanceMeasures.L1
        assert l1_conv.threshold == 0.234

        l2_with_limit = BaseClient().get_iterator(
            "l2-convergence-0.234-limit-9"
        )
        assert isinstance(l2_with_limit, ConvergenceIterator)
        assert l2_with_limit.distance_measure == DistanceMeasures.L2
        assert l2_with_limit.threshold == 0.234
        assert l2_with_limit.limit == 9

        invalid_it_strings = (
            "fixed",
            "fixed-",
            "fixed-hello",
            "fixed-10.0",
            "fixed--4",
            "convergence",
            "-convergence-",
            "l1-convergence-",
            "l1-convergence-l1",
            "blah-convergence-0.03",
            "l1-convergence-0.03-limit",
            "l1-convergence-0.03-limit-",
            "l1-convergence-0.03-limit-45.0"
        )
        for it_string in invalid_it_strings:
            with pytest.raises(ValueError):
                BaseClient().get_iterator(it_string)

    def test_get_algorithm_parameter(self):
        # Iterator param
        name1, val1 = BaseClient().algorithm_parameter("iterator=fixed-99")
        assert name1 == "iterator"
        assert isinstance(val1, FixedIterator)
        assert val1.limit == 99

        # Priors
        name2, val2 = BaseClient().algorithm_parameter("priors=voted")
        assert name2 == "priors"
        assert val2 == PriorBelief.VOTED

        # Anything else should be a float
        name3, val3 = BaseClient().algorithm_parameter("g=1.4")
        assert name3 == "g"
        assert val3 == 1.4

        # Extra whitespace should be allowed
        name3, val3 = BaseClient().algorithm_parameter("ppp =   3.4")
        assert name3 == "ppp"
        assert val3 == 3.4

    def test_get_output_obj(self, csv_dataset):
        dataset = MatrixDataset.from_csv(csv_dataset)
        alg = Sums(iterator=FixedIterator(5))
        # Default should be all fields if none are given, but not accuracy
        # unless supervised data given
        results = alg.run(dataset)
        out1 = BaseClient().get_output_obj(results)
        exp_keys = {
            f.value for f in OutputFields if f != OutputFields.ACCURACY
        }
        assert set(out1.keys()) == exp_keys

        sup_data = SupervisedData.from_csv(csv_dataset)
        sup_results = alg.run(sup_data.data)
        out2 = BaseClient().get_output_obj(sup_results, sup_data=sup_data)
        assert set(out2.keys()) == {f.value for f in OutputFields}
        assert out2["trust"] == sup_results.trust
        assert out2["belief"] == sup_results.belief

        out3 = BaseClient().get_output_obj(
            results, output_fields=[OutputFields.TRUST]
        )
        assert set(out3.keys()) == {"trust"}


class TestCommandLineClient(ClientTestsBase):
    @pytest.fixture
    def client(self):
        return CommandLineClient()

    def run(self, *args):
        client = CommandLineClient()
        client.run(args)

    def get_parsed_args(self, *args):
        return CommandLineClient().get_parser().parse_args(args)

    def test_no_commands(self, capsys):
        self.run()
        out = capsys.readouterr().out
        assert "Command-line interface to truthdiscovery library" in out

    def test_basic(self, csv_dataset):
        self.run(
            "run", "--algorithm", "sums", "-f", csv_dataset
        )

    def test_results(self, csv_dataset, capsys):
        self.run(
            "run", "-a", "average_log", "-f", csv_dataset
        )
        got_results = yaml.load(capsys.readouterr().out)
        exp_results = AverageLog().run(MatrixDataset.from_csv(csv_dataset))
        assert got_results["trust"] == exp_results.trust
        assert got_results["belief"] == exp_results.belief
        assert got_results["iterations"] == exp_results.iterations

    def test_multiple_parameters(self, csv_dataset):
        self.run(
            "run", "--algorithm", "pooled_investment", "-p", "g=1.1234",
            "iterator=fixed-11", "priors=uniform", "-f", csv_dataset
        )

    def test_get_algorithm_instance(self, client, csv_dataset):
        args = self.get_parsed_args(
            "run", "--algorithm", "truthfinder", "-p", "dampening_factor=0.1",
            "influence_param=0.77", "-f", csv_dataset
        )
        alg = client.get_algorithm_object(args)
        assert isinstance(alg, TruthFinder)
        assert alg.dampening_factor == 0.1
        assert alg.influence_param == 0.77

    def test_set_prior_belief(self, client, csv_dataset, capsys):
        args = self.get_parsed_args(
            "run", "--algorithm", "sums", "-p", "priors=voted", "-f",
            csv_dataset
        )
        alg = client.get_algorithm_object(args)
        assert isinstance(alg, Sums)
        assert alg.priors == PriorBelief.VOTED

        # Invalid prior string
        with pytest.raises(SystemExit):
            self.run(
                "run", "--algorithm", "sums", "-p", "priors=blah", "-f",
                csv_dataset
            )

        err_msg = capsys.readouterr().err
        assert "'blah' is not a valid PriorBelief" in err_msg

    def test_set_iterator(self, client, csv_dataset, capsys):
        # Fixed iterator
        raw_args1 = (
            "run", "--algorithm", "sums", "-p", "iterator=fixed-123", "-f",
            csv_dataset
        )
        args1 = self.get_parsed_args(*raw_args1)
        alg1 = client.get_algorithm_object(args1)
        assert isinstance(alg1, Sums)
        assert isinstance(alg1.iterator, FixedIterator)
        assert alg1.iterator.limit == 123
        self.run(*raw_args1)
        results = yaml.load(capsys.readouterr().out)
        assert results["iterations"] == 123

        # Convergence iterator
        args2 = self.get_parsed_args(
            "run", "--algorithm", "sums", "-p",
            "iterator=cosine-convergence-0.01", "-f", csv_dataset
        )
        alg2 = client.get_algorithm_object(args2)
        assert isinstance(alg2.iterator, ConvergenceIterator)
        assert alg2.iterator.distance_measure == DistanceMeasures.COSINE
        assert alg2.iterator.threshold == 0.01

        # Convergence iterator with limit
        args3 = self.get_parsed_args(
            "run", "--algorithm", "sums", "-p",
            "iterator=l2-convergence-0.3-limit-99", "-f", csv_dataset
        )
        alg3 = client.get_algorithm_object(args3)
        assert isinstance(alg3.iterator, ConvergenceIterator)
        assert alg3.iterator.distance_measure == DistanceMeasures.L2
        assert alg3.iterator.threshold == 0.3
        assert alg3.iterator.limit == 99

        # Convergence iterator with invalid distance measure
        with pytest.raises(SystemExit):
            self.run(
                "run", "--algorithm", "sums", "-p",
                "iterator=blah-convergence-0.3-limit-99", "-f", csv_dataset
            )
        assert "invalid distance measure 'blah'" in capsys.readouterr().err

        # Invalid iterator specification
        with pytest.raises(SystemExit):
            self.run(
                "run", "--algorithm", "sums", "-p", "iterator=hello", "-f",
                csv_dataset
            )
        assert "invalid iterator specification" in capsys.readouterr().err

    def test_invalid_algorithm_parameter(self, csv_dataset, capsys):
        # Invalid name
        with pytest.raises(SystemExit):
            self.run(
                "run", "--algorithm", "truthfinder", "-p", "myextraparm=0.1",
                "-f", csv_dataset
            )
        err = capsys.readouterr().err
        assert "invalid parameter" in err
        assert "myextraparm" in err

        # Invalid format
        with pytest.raises(SystemExit):
            self.run(
                "run", "--algorithm", "truthfinder", "-p", "initial_trust 0.1",
                "-f", csv_dataset
            )
        assert "must be in the form 'key=value'" in capsys.readouterr().err

    def test_invalid_algorithm(self, csv_dataset, capsys):
        with pytest.raises(SystemExit):
            self.run(
                "run", "--algorithm", "joesalgorithm", "-f", csv_dataset
            )
        assert (
            "invalid algorithm label 'joesalgorithm'"
            in capsys.readouterr().err
        )

    def test_filter_sources_variables(self, csv_dataset, capsys):
        # Filter sources
        self.run(
            "run", "-a", "sums", "-f", csv_dataset, "--sources", "0", "3",
        )
        results1 = yaml.load(capsys.readouterr().out)
        assert set(results1["trust"].keys()) == {0, 3}
        assert set(results1["belief"].keys()) == {0, 1, 2, 3}

        # Filter both
        self.run(
            "run", "-a", "sums", "-f", csv_dataset, "--sources", "0", "3",
            "--variables", "1", "2"
        )
        results2 = yaml.load(capsys.readouterr().out)
        assert set(results2["trust"].keys()) == {0, 3}
        assert set(results2["belief"].keys()) == {1, 2}

        # Special case where only one source/variable
        self.run(
            "run", "-a", "sums", "-f", csv_dataset, "--sources", "1",
            "--variables", "0"
        )
        results3 = yaml.load(capsys.readouterr().out)
        assert set(results3["trust"].keys()) == {1}
        assert set(results3["belief"].keys()) == {0}

        # Unknown sources/vars should not cause trouble
        self.run(
            "run", "-a", "sums", "-f", csv_dataset, "--sources", "3", "1000",
            "--variables", "499", "666"
        )
        results3 = yaml.load(capsys.readouterr().out)
        assert set(results3["trust"].keys()) == {3}
        # We didn't give any valid variables: belief should be empty
        assert results3["belief"] == {}

    def test_default_output(self, csv_dataset, capsys):
        self.run("run", "-a", "voting", "-f", csv_dataset)
        results = yaml.load(capsys.readouterr().out)
        assert set(results.keys()) == {
            "time", "iterations", "trust", "belief"
        }

    def test_custom_output(self, csv_dataset, capsys):
        self.run("run", "-a", "sums", "-f", csv_dataset, "-o", "time")
        results = yaml.load(capsys.readouterr().out)
        assert set(results.keys()) == {"time"}

        self.run(
            "run", "-a", "sums", "-f", csv_dataset, "-o", "time",
            "iterations"
        )
        results = yaml.load(capsys.readouterr().out)
        assert set(results.keys()) == {"time", "iterations"}

        self.run(
            "run", "-a", "sums", "-f", csv_dataset, "-o", "trust",
            "trust_stats"
        )
        results = yaml.load(capsys.readouterr().out)
        assert set(results.keys()) == {"trust", "trust_stats"}
        exp_mean, exp_stddev = (Sums().run(MatrixDataset.from_csv(csv_dataset))
                                .get_trust_stats())
        assert results["trust_stats"] == {
            "mean": exp_mean, "stddev": exp_stddev
        }

    def test_show_most_believed_values(self, csv_dataset, capsys):
        self.run(
            "run", "-a", "voting", "-f", csv_dataset, "--output",
            "most_believed_values"
        )
        results = yaml.load(capsys.readouterr().out)
        assert results == {
            "most_believed_values": {0: [1, 2, 3], 1: [2], 2: [1, 3], 3: [2]}
        }
        # Test with variable filtering
        self.run(
            "run", "-a", "voting", "-f", csv_dataset, "-o",
            "most_believed_values", "--variables", "0", "3"
        )
        results = yaml.load(capsys.readouterr().out)
        assert "belief" not in results
        assert "most_believed_values" in results
        assert results["most_believed_values"] == {
            0: [1, 2, 3],
            3: [2]
        }

    def test_belief_stats(self, csv_dataset, capsys):
        self.run("run", "-a", "sums", "-f", csv_dataset, "-o", "belief_stats")
        results = yaml.load(capsys.readouterr().out)
        assert set(results.keys()) == {"belief_stats"}
        exp_belief_stats = (Sums().run(MatrixDataset.from_csv(csv_dataset))
                            .get_belief_stats())
        assert results["belief_stats"] == {
            var: {"mean": mean, "stddev": stddev}
            for var, (mean, stddev) in exp_belief_stats.items()
        }

    def test_synthetic_generation(self, capsys):
        self.run(
            "synth", "--trust", "0.5", "0.6", "0.7", "--num-vars", "10",
            "--domain-size", "5"
        )
        output = capsys.readouterr().out.strip()
        lines = output.split("\n")
        print(output)
        assert len(lines) == 4  # first row is true values, then 3 source rows
        for line in lines:
            columns = line.split(",")
            assert len(columns) == 10
            for col in columns:
                assert col == "" or float(col) in {0, 1, 2, 3, 4}

    def test_synthetic_generation_claim_prob_1(self, capsys):
        self.run(
            "synth", "--trust", "0.5", "0.6", "0.7", "--num-vars", "10",
            "--domain-size", "2", "--claim-prob", "1"
        )
        output = capsys.readouterr().out.strip()
        lines = output.split("\n")
        assert len(lines) == 4
        for line in lines:
            columns = line.split(",")
            for col in columns:
                assert float(col) in {0, 1}

    def test_synthetic_generation_source_trust_1(self, capsys):
        self.run("synth", "--trust", "1", "--claim-prob", "1")
        output = capsys.readouterr().out.strip()
        true_vals, claims = output.split("\n")
        assert true_vals == claims

    def test_synthetic_generation_invalid_params(self, capsys):
        # Check that invalid param errors are caught by the parser, not raised
        # as Python exceptions
        with pytest.raises(SystemExit):
            self.run("synth", "--trust", "2")
        exp_err_msg = "error: Trust values must be in [0, 1]"
        assert exp_err_msg in capsys.readouterr().err

    def test_supervised_dataset_and_accuracy(self, csv_dataset, capsys):
        self.run(
            "run", "-a", "voting", "-f", csv_dataset, "--supervised", "-o",
            "trust", "belief", "accuracy"
        )
        results = yaml.load(capsys.readouterr().out)
        assert results["trust"] == {0: 1, 1: 1, 2: 1}
        assert results["belief"] == {
            0: {2: 1, 3: 1},
            1: {1: 1, 2: 1},
            2: {1: 1},
            3: {2: 1, 3: 1}
        }
        # accuracy is not deterministic when there are ties for most-believed
        # values
        assert results["accuracy"] in (1 / 3, 2 / 3, 0)

    def test_accuracy_not_supervised(self, csv_dataset, capsys):
        with pytest.raises(SystemExit):
            self.run(
                "run", "-a", "voting", "-f", csv_dataset, "-o", "accuracy"
            )
        err_msg = "cannot calculate accuracy without --supervised"
        assert err_msg in capsys.readouterr().err

    def test_accuracy_undefined(self, capsys, tmpdir):
        ds = tmpdir.join("newdata.csv")
        ds.write("\n".join((
            "1,2,3,4",
            "1,2,3,4",
        )))
        self.run("run", "-a", "voting", "-f", str(ds), "-s", "-o", "accuracy")
        results = yaml.load(capsys.readouterr().out)
        assert results["accuracy"] is None
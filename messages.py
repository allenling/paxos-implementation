
import dataclasses
import json

MSG_MAP = {}


def dataclass_from_dict(klass, d):
    # https://stackoverflow.com/a/54769644/3197067
    try:
        fieldtypes = {f.name: f.type for f in dataclasses.fields(klass)}
        return klass(**{f: dataclass_from_dict(fieldtypes[f], d[f]) for f in d})
    except:
        return d # Not a dataclass field


class MessageMeta(type):

    def __new__(cls, class_name, parents, attrs):
        global MSG_MAP
        cls_obj = super().__new__(cls, class_name, parents, attrs)
        MSG_MAP[class_name] = cls_obj
        return cls_obj


@dataclasses.dataclass
class Msg(metaclass=MessageMeta):

    MSG_NAME = "msg_name"

    def to_dict(self):
        data = {self.MSG_NAME: self.__class__.__name__,
                "data": dataclasses.asdict(self),
                }
        return data

    def to_str(self):
        return json.dumps(self.to_dict())

    def to_bytes(self):
        return self.to_str().encode()

    @classmethod
    def from_str(cls, data):
        jdata = json.loads(data)
        return cls.from_dict(jdata)

    @classmethod
    def from_dict(cls, jdata):
        name = jdata[cls.MSG_NAME]
        cmd_cls = MSG_MAP[name]
        obj = dataclass_from_dict(cmd_cls, jdata["data"])
        return obj


@dataclasses.dataclass
class GetBallotNumberReq(Msg):
    least: int = -1


@dataclasses.dataclass
class GetBallotNumberResp(Msg):
    ballot_number: int


@dataclasses.dataclass
class StartPropose(Msg):
    value: str
    accs_idx: list | None = None
    debug: bool = False


@dataclasses.dataclass
class Proposal(Msg):
    ballot_number: int


@dataclasses.dataclass
class Promised(Msg):
    max_accepted_number: int | None
    value: str | None


@dataclasses.dataclass
class Rejected(Msg):
    ballot_number: int | None


@dataclasses.dataclass
class AcceptReq(Msg):
    ballot_number: int
    value: str


@dataclasses.dataclass
class AcceptRejected(Msg):
    ballot_number: int | None


@dataclasses.dataclass
class AcceptSucc(Msg):
    ballot_number: int


@dataclasses.dataclass
class Close(Msg):
    pass


@dataclasses.dataclass
class StartLearn(Msg):
    pass


@dataclasses.dataclass
class LearnReq(Msg):
    pass


@dataclasses.dataclass
class LearnResp(Msg):
    value: str | None = None
    msg: str | None = None


@dataclasses.dataclass
class AccpetedInfo(Msg):
    max_accepted_bn: int | None
    value: str | None


@dataclasses.dataclass
class P1ResumeReq(Msg):
    p1_accs_idx: list | None = None
    p2_accs_idx: list | None = None


@dataclasses.dataclass
class WaitP1PausedReq(Msg):
    pass


@dataclasses.dataclass
class P2ResumeReq(Msg):
    p1_accs_idx: list | None = None
    p2_accs_idx: list | None = None


@dataclasses.dataclass
class WaitP2PausedReq(Msg):
    pass


@dataclasses.dataclass
class WaitChosenReq(Msg):
    pass


@dataclasses.dataclass
class ShowInfo(Msg):
    pass


def main():
    return


if __name__ == "__main__":
    main()

using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Linq;
using System.Text;
using CHoops;
using CHoopsStatic.RefdataGeneral_package;
using mbl.tnc.common;
using mbl.tnc.common.framework.core;
using mbl.tnc.common.ui.devx.controls.assetSelector;
using mbl.tnc.common.ui.devx.controls.assetSelector.handler;
using mbl.tnc.dst.dealentry;
using mbl.tnc.dst.dealentry.actionmodule;
using mbl.tnc.dst.dealentry.validation.validationrules;
using mbl.tnc.dst.deals.energy.core;
using mbl.tnc.dst.deals.energy.core.common.power;
using mbl.tnc.dst.deals.energy.core.devx;
using mbl.tnc.dst.deals.energy.core.utils;
using mbl.tnc.dst.deals.uspower.dealentry.shared.model;
using mbl.tnc.dst.deals.uspower.Properties;
using mbl.tnc.dst.mvp.Model.Validation;
using mbl.tnc.dst.utilities;
using mbl.tnc.dst.utilities.devx.forms;
using mbl.tnc.generics.alldeals;
using mbl.tnc.generics.energy;
using Newtonsoft.Json;

namespace mbl.tnc.dst.deals.uspower.dealentry.transport
{
    public partial class TransmissionWrapper : BaseUSPowerDealWrapper,
        ITransmissionScheduler<TransmissionWrapper>,
        ICustomCharges,
        IRunPayment,
        IAssetSelectorRequester,
        ITransportDeal,
        IUSPowerTransportElementCharges
    {
        #region Vars

        public Guid Id = Guid.NewGuid();

        private bool _inMemoryDealWithChildren = false;

        private bool _requiresScheduleRegeneration = false;
        private const string us_power_transmission_deal = "us_power_transmission_deal";
        private const string default_product_type = "ENERGY";
        private const string default_service_level = "Firm Transmission";

        public TransmissionAssetsHelper AssetsHelper;
        public PaymentDateCalculator PDCalculator;
        public TransmissionScheduleGenerator ScheduleGenerator;
        public CommentMediator CommentMediator;

        #endregion Vars

        #region Constructors

        public TransmissionWrapper(CoreWrap coreWrap)
            : base(coreWrap)
        {

            if (coreWrap.DealContainer == null)
                this.DealContainer.Deal._Discriminator_ = AnyDealEnum.energy_transport;

            // Register Wrapper Step Functions
            AddStepFunction(new CounterpartyStepFunction());
            AddStepFunction(new GlobalPaymentTermStepFunction());
            AddStepFunction(new AssetPointStepFunction());
            AddStepFunction(new EnabledBlocksTypeStepFunction());
            AddStepFunction(new ScheduleRegenerationRequiredStepFunction());
            AddStepFunction(new TransmissionSchedulesStepFunction());
            AddStepFunction(new ReservationChargeStepFunction());
            AddStepFunction(new TransportMaxRateStepFunction());
            // AddStepFunction(new CommentStepFunction());
            AddStepFunction(new GlobalCommentStepFunction());

            // We will need to override the PaymentDateExpression here
            if (Deal.payment_date_expr == "NG_US_SETTLEMENT")
            {
                Deal.payment_date_expr = string.Empty;
            }

            this.GlobalPaymentTerm = "US_TRM_23_DAYS_AFTER_MONTH_END";
            this.AllowChildCloseout = true;

            if (string.IsNullOrEmpty(this.DemandChargeType)) this.DemandChargeType = EnergyCoreEditors.MaxTariffRate;

            AssetsHelper = new TransmissionAssetsHelper(this);
            PDCalculator = new PaymentDateCalculator(this);
            ScheduleGenerator = new TransmissionScheduleGenerator(this);
            CommentMediator = new CommentMediator(this);

            if (Child != 0) return;

            // Below applies only to the first child (Child 0)
            using (new DynamicPropertyObjectEventSuppressor(this))
            {
                InitDeliveryAndReceiptPointGroups();
                FetchDBChildWrappers();
            }

            ProcessInMemoryCoresAsChildren(coreWrap.ExtraCores);
            GenerateTransmissionSchedulesFromChildren();
            ApplySnapshot();
        }

        private void InitDeliveryAndReceiptPointGroups()
        {
            this.DeliveryPoint = TransmissionAssetsHelper.ScrapToLocation(Deal.delivery_point);
            this.ReceivingPoint = TransmissionAssetsHelper.ScrapToLocation(Deal.receiving_point);
        }

        public IList DeliveryPointGroupDataSource
        {
            get { return TransmissionAssetsHelper.GetUSPowerAssetsFilteredForLocationOnly().AsReadOnly(); }
        }

        public IList ReceivingPointGroupDataSource
        {
            get { return TransmissionAssetsHelper.GetUSPowerAssetsFilteredForLocationOnly().AsReadOnly(); }
        }

        private void ProcessInMemoryCoresAsChildren(List<CoreWrap> extraCores)
        {
            if (this.IsInDB || extraCores == null || extraCores.Count == 0) return;

            if (this.Child != 0) return;

            _inMemoryDealWithChildren = true;

            foreach (var ec in extraCores)
            {
                var childWrap = new TransmissionWrapper(ec);
                this.AddChildWrapper(childWrap, false);
            }

            extraCores.Clear();
        }

        #endregion

        #region properties

        public Transport Deal => this.DealContainer.Deal.energy_transport;

        public TransportElement SingleTransportElement => Deal?.elements?.FirstOrDefault() ?? new TransportElement();

        public bool RequiresScheduleRegeneration
        {
            get => _requiresScheduleRegeneration;
            set
            {
                if (_requiresScheduleRegeneration == value) return;

                _requiresScheduleRegeneration = value;
                FirePropertyChangedEvent(nameof(RequiresScheduleRegeneration));
            }
        }

        public IntradayEnabledBlocksEnum EnabledBlocksType
        {
            get => Deal.enabled_blocks._Discriminator_;
            set
            {
                if (this.Deal.enabled_blocks._Discriminator_ == value) return;

                this.Deal.enabled_blocks._Discriminator_ = value;
                FirePropertyChangedEvent(nameof(EnabledBlocksType));
            }
        }

        public bool IsDayAhead
        {
            get { return AssetsHelper.IsDayAhead; }
            set { AssetsHelper.IsDayAhead = value; }
        }

        public string DAorRTChoice
        {
            get { return IsDayAhead ? TransportConstants.DayAhead : TransportConstants.RealTime; }
            set { this.AssetsHelper.IsDayAhead = string.Equals(TransportConstants.DayAhead, value); }
        }

        private string _receivingPoint = string.Empty;

        /// <summary>
        /// The UI value for the chosen Receiving Point Location. Has no Schedule Type of Day-Ahead/Real-Time information
        /// </summary>
        public string ReceivingPoint
        {
            get
            {
                if (_receivingPoint == string.Empty && !string.IsNullOrEmpty(this.Deal?.receiving_point))
                {
                    _receivingPoint = TransmissionAssetsHelper.ScrapToLocation(this.Deal.receiving_point);
                }

                return _receivingPoint;
            }
            set
            {
                if (_receivingPoint == value) return;

                if (string.IsNullOrEmpty(_receivingPoint))
                {
                    _receivingPoint = value;
                    return;
                }
                
                _receivingPoint = value;
                FirePropertyChangedEvent(nameof(ReceivingPoint));
            }
        }

        private string _deliveryPoint = string.Empty;

        /// <summary>
        /// The UI value for the chosen Delivery Point Location. Has no Schedule Type of Day-Ahead/Real-Time information
        /// </summary>
        public string DeliveryPoint
        {
            get
            {
                if (_deliveryPoint == string.Empty && !string.IsNullOrEmpty(this.Deal?.delivery_point))
                {
                    _deliveryPoint = TransmissionAssetsHelper.ScrapToLocation(this.Deal.delivery_point);
                }

                return _deliveryPoint;
            }
            set
            {
                if (_deliveryPoint == value) return;

                if (string.IsNullOrEmpty(_deliveryPoint))
                {
                    _deliveryPoint = value;
                    return;
                }
                
                _deliveryPoint = value;
                FirePropertyChangedEvent(nameof(DeliveryPoint));
            }
        }

        public bool IsBuy
        {
            get => !Deal.sold;
            set => Deal.sold = !value;
        }

        /// <summary>
        /// Whether the schedule type is locked to ATC due to Delivery and Receipt Points mismatchs over their Regions
        /// </summary>

        public DateTime StartDate
        {
            get => Deal.start_date;
            set
            {
                if (Deal.start_date == value) return;

                Deal.start_date = value;
                FirePropertyChangedEvent(nameof(StartDate));
            }
        }

        public DateTime EndDate
        {
            get => Deal.end_date;
            set
            {

                if (Deal.end_date == value) return;

                Deal.end_date = value;
                FirePropertyChangedEvent(nameof(EndDate));
            }
        }


        private string _globalComment = string.Empty;
        public string GlobalComment
        {
            get => _globalComment;
            set
            {
                if (string.Equals(_globalComment, value)) return;

                _globalComment = value;
                FirePropertyChangedEvent(nameof(GlobalComment));
            }
        }

        public void SetDealComment(string comment)
        {
            base.Comment = comment;
        }

        public string GetDealComment()
        {
            return base.Comment;
        }
        
        public override string Comment
        {
            get => CommentMediator?.Comment ?? string.Empty;
            set
            {
                if (CommentMediator.Comment == value) return;

                CommentMediator.Comment = value;

                FirePropertyChangedEvent(nameof(Comment));
            }
        }

        public string Location
        {
            get
            {
                if (!string.IsNullOrEmpty(SingleTransportElement.delivery_point))
                {
                    return CoreMts.MTSFacade.MTSRefData.Commodities.GetCommodity(SingleTransportElement.delivery_point).rateset_centres;
                }
                return "days";
            }
        }

        public string[] Locations
        {
            get
            {
                string location = this.Location;

                if (!location.Contains("(") && location.Contains(","))
                    return location.Split(',');
                else
                    return new string[] { this.Location };
            }
        }

        private double _lossRatePercentage = 0.0;
        public double LossRatePercentage
        {
            get => _lossRatePercentage;
            set
           {
                if (_lossRatePercentage == value) return;

                if (_lossRatePercentage == 0.0)
                {
                    _lossRatePercentage = value;
                    return;
                }
                
                _lossRatePercentage = value;
                FirePropertyChangedEvent(nameof(LossRatePercentage));
            }
        }

        public double ReservationCharge
        {
            get => this.Deal.reservation_charge;
            set
            {
                if (this.Deal.reservation_charge == value) return;

                this.Deal.reservation_charge = value;
                FirePropertyChangedEvent(nameof(ReservationCharge));
            }
        }

        public string ReservationChargeUnit
        {
            get => Deal.reservation_charge_unit;
            set
            {
                if (this.Deal.reservation_charge_unit == value) return;

                    this.Deal.reservation_charge_unit = value;
                    FirePropertyChangedEvent(nameof(ReservationChargeUnit));
            }
        }

        private double _transportMaxRate = 0.0;
        /// <summary>
        /// The value to capture in the transport_max_rate Tag. It is not a field in the Energy Transport deal type in MTS
        /// </summary>
        public double TransportMaxRate
        {
            get => _transportMaxRate;
            set
            {
                if (_transportMaxRate == value || value == 0.0) return;

                if (_transportMaxRate == 0.0)
                {
                    _transportMaxRate = value;
                    return;
                }
                
                _transportMaxRate = value;
                FirePropertyChangedEvent(nameof(TransportMaxRate));
            }
        }

        private string _volumeUnit = string.Empty;
        public string VolumeUnit
        {
            get => _volumeUnit;
            set
            {
                if(_volumeUnit == value) return;

                _volumeUnit = value;
                FirePropertyChangedEvent(nameof(VolumeUnit));
            }
        }


        private double _volume = 0.0;
        /// <summary>
        /// This is the Volume per DAY. This is how it is stored in MTS for such deals
        /// </summary>
        public double Volume
        {
            get => _volume;
            set
            {
                if (_volume == value) return;

                _volume = value;
                FirePropertyChangedEvent(nameof(Volume));
            }
        }

        private double _volumePerHour = 0.0;
        public double VolumePerHour
        {
            get
            {
                return _volumePerHour;
            }
            set
            {
                _volumePerHour = value;
            }
        }

        public override string Counterparty
        {
            get => base.Counterparty;
            set
            {
                if (base.Counterparty == value) return;

                base.Counterparty = value;
                FirePropertyChangedEvent(nameof(Counterparty));
            }
        }

        protected static List<PaymentTerm> _usPowerPaymentTerms = null;
        private List<TransmissionPaymentTermOption> _usPowerPaymentTermOptions = null;
        public List<TransmissionPaymentTermOption> USPowerPaymentTermOptions
        {
            get
            {
                if (_usPowerPaymentTerms == null)
                {
                    if (this.CoreMts?.MTSFacade?.MTSRefData?.MTSRefData_General != null)
                    {
                        var allPaymentTerms = this.CoreMts?.MTSFacade?.MTSRefData?.MTSRefData_General.getPdeTerms();

                        if (allPaymentTerms != null)
                        {
                            _usPowerPaymentTerms = allPaymentTerms.Where(pt => pt.group == TransportConstants.USPowerPDEGroupName).ToList();
                        }
                    }
                }

                if (_usPowerPaymentTerms != null)
                {
                    _usPowerPaymentTermOptions = _usPowerPaymentTerms.Select(pt => new TransmissionPaymentTermOption(pt)).ToList();
                }

                return _usPowerPaymentTermOptions ?? new List<TransmissionPaymentTermOption>();
            }
        }

        private string _globalPaymentTerm = null;
        public string GlobalPaymentTerm
        {
            get
            {
                return _globalPaymentTerm ?? TransportConstants.NoTerm;
            }
            set
            {
                if (_globalPaymentTerm == value) return;

                
                if (string.IsNullOrEmpty(_globalPaymentTerm))
                {
                    _globalPaymentTerm = value;
                    return;
                }

                _globalPaymentTerm = value;
                FirePropertyChangedEvent(nameof(GlobalPaymentTerm));
            }
        }

        public TransportFuelTypeEnum TransportElementFuelPaymentType
        {
            get => SingleTransportElement.fuel_payment_type._Discriminator_;
            set
            {
                if (SingleTransportElement.fuel_payment_type._Discriminator_ == value) return;
                
                SingleTransportElement.fuel_payment_type._Discriminator_ = value;
                FirePropertyChangedEvent(nameof(TransportElementFuelPaymentType));
            }
        }

        public string DemandChargeType
        {
            get => GetTagValue("transport_dem_charge_rate_type");
            set
            {
                if (DemandChargeType == value) return;

                SetTagValue("transport_dem_charge_rate_type", value);
                FirePropertyChangedEvent(nameof(DemandChargeType));
            }
        }

        #endregion

        public static double CanEdit(CoreWrap coreWrap)
        {
            var dc = coreWrap.DealContainer;

            return dc.Deal._Discriminator_ == AnyDealEnum.energy_transport ? 0.5 : 0;
        }

        public static bool DealGroupPredicate(CoreMts coreMts, List<DealContents> dealContentList)
        {
            //All deals must be cashflows
            if (dealContentList.Any(d => d.DC.Deal._Discriminator_ != AnyDealEnum.energy_transport))
                return false;

            //Must have deal-level tags
            if (dealContentList.First().DealTags == null)
                return false;

            return true;
        }

        #region Init Process
        protected override void InitLocalVars()
        {
            base.InitLocalVars();
            EnablePDEGroupTag = true;
            DealTypeId = mts.deals.DealTypeId.energy_transport;
            Currency = Deal.currency;
        }

        protected override void InitializeData(CoreWrap coreWrap)
        {
            base.InitializeData(coreWrap);
            InitEnergyTransportLocalVars();

            if (string.IsNullOrEmpty(this.FercProductType)) this.FercProductType = default_product_type;
            if (string.IsNullOrEmpty(this.ServiceLevel)) this.ServiceLevel = default_service_level;
        }

        private void InitEnergyTransportLocalVars()
        {
            Volume = this.Deal.capacity_volume;
            VolumeUnit = this.Deal.capacity_volume_unit;

            if (this.Deal?.elements?.Count > 0)
            {
                LossRatePercentage = this.Deal.elements?[0].loss_rate_percentage ?? 0.0;
            }

            _tagUpdates(this);
            InitializeTransportElementsFromDeal();
        }

        protected override void ProcessLocalVars()
        {
            base.ProcessLocalVars();
            ApplyIsBuyOnVolume();
        }

        public override string Currency { get => Deal.currency; }

        private void ApplyIsBuyOnVolume()
        {
            foreach (ExplicitIntradayDelivery delivery in Deal.enabled_blocks.customs)
            {
                delivery.volume = Math.Abs(delivery.volume) * (IsBuy ? 1D : -1D);
            }

            foreach (TransportActual actual in Deal.actuals.actuals)
            {
                actual.delivered_volume = Math.Abs(actual.delivered_volume) * (IsBuy ? 1D : -1D);
            }

            foreach (TransportIntradayActual intradayActual in Deal.actuals.intraday_actuals)
            {
                intradayActual.delivered_volume = Math.Abs(intradayActual.delivered_volume) * (IsBuy ? 1D : -1D);
            }

            for (int i = 0; i < Deal.elements.Count; i++)
            {
                Deal.elements[i].volume = Math.Abs(Deal.elements[i].volume) * (IsBuy ? 1D : -1D);
            }
        }

        public void FetchDBChildWrappers()
        {
            // If not in DB, no Child to load
            if (!this.IsInDB) return;

            this.ChildWrappers.Clear();

            // Now, load all the children
            var children = DealEntryUtils.GetSiblingDeals(this, DBDealType.H_ALL_TYPES, typeof(TransmissionWrapper))
                ?.Where(c => !c.IsClosedOut).ToList();
            children?.ForEach(c => this.AddChildWrapper(c, false));
        }

        #endregion Init Process

        public override bool ProcessBeforeAnyFormAction()
        {
            // Only apply this logic for root deal, child 0
            if (Child > 0) return true;

            if (RequiresScheduleRegeneration)
            {
                DSAMsgBox.Warn(
                    "Generated Transmission Schedules are stale. Please regenerate the schedules to continue.");
                return false;
            }

            if (TransmissionSchedules == null || TransmissionSchedules.Count == 0) return false;

            TakeSnapshot();

            // Setting up our Child 0
            var firstSchedule = TransmissionSchedules[0];

            this.Deal.delivery_point =
                AssetsHelper.DecoratePointByScheduleType(this._deliveryPoint, firstSchedule.ScheduleType);
            this.Deal.receiving_point =
                AssetsHelper.DecoratePointByScheduleType(this._receivingPoint, firstSchedule.ScheduleType);
            this.InitializeNewTransportElementsCollection();

            if (!_inMemoryDealWithChildren && ChildWrappers.Count > 0 && TransmissionSchedules.Any(ts => ts.IsDirty))
            {
                ChildWrappers.Clear();
                FetchDBChildWrappers();
            }

            var lastChildNum = ChildWrappers?.Count() > 0 ? ChildWrappers.Count() + 1 : 1;

            // We are updating our Child 0 to reflect the first Schedule. It will be reverted back after Event handling (e.g. Save) is completed
            this.Deal.start_date = firstSchedule.ScheduleDate;
            this.Deal.end_date = firstSchedule.ScheduleDate;
            this.Deal.enabled_blocks._Discriminator_ = firstSchedule.ScheduleType;

            this.VolumePerHour = firstSchedule.VolumePerHour;
            this.Deal.capacity_volume = firstSchedule.Volume;
            this.Deal.capacity_volume_unit = firstSchedule.VolumeUnit;
            this.Deal.payment_date_expr = DateUtils.toMTSDateString(firstSchedule.PaymentDate);

            this.SingleTransportElement.volume = firstSchedule.Volume;
            this.SingleTransportElement.volume_unit = firstSchedule.VolumeUnit;
            this.SingleTransportElement.loss_rate_percentage = firstSchedule.LossRate;
            this.SingleTransportElement.delivery_point = this.Deal.delivery_point;
            this.SingleTransportElement.receiving_point = this.Deal.receiving_point;
            this.SingleTransportElement.contract_type = TransportConstants.USPowerTransportElementContractType;
            // For setting the Comment, we need the help of the Mediator
            this.CommentMediator.SetMode(ContentMediatorMode.DealCommentOnly);
            this.Comment = firstSchedule.Comment;
            this.CommentMediator.SetMode(ContentMediatorMode.General);
            this.MarkAsDirty();
            this.AssetsHelper.SetEnabledDateExpr(this);

            //TC-14683: pde_term & Payment Date error - First Main Deal pde_overide = true - pde_term = "DoNotRunPaymentEngine"
            this.MTSPaymentEngineContext.IsDoNotRun = true;

            _modelAction(this);
            _tagUpdates(this);

            // Charges have changed; mark all Schedules as dirty
            if (SetCustomChargesAndReport(this, this._transportElementCharges))
            {
                TransmissionSchedules.ForEach(ts => ts.IsDirty = true);
            }

            if (TransmissionSchedules.Count > 0)
            {
                // See if we may need to CloseOut Children that are now out of Schedules Dates
                var minDate = TransmissionSchedules.Select(t => t.ScheduleDate).Min();
                var maxDate = TransmissionSchedules.Select(t => t.ScheduleDate).Max();

                // Find out the Deals that will be Closed. First, start with Deals that lie outside the Date range
                var dealsToClose = this.ChildWrappers?.Select(cw => cw as TransmissionWrapper)
                                                      .Where(cw => cw.StartDate < minDate || cw.EndDate > maxDate)
                                                      .ToList();

                var newChildren = new List<TransmissionWrapper>();

                using (var disposableCursor = new mbl.tnc.common.DisposableCursor("Generating or Updating Children"))
                {
                    var showMsg = TransmissionSchedules.Count > 10;
                    int count = TransmissionSchedules.Count;

                    // Update or Add Children
                    for (int dn = 1; dn < TransmissionSchedules.Count; dn++)
                    {
                        if (showMsg)
                        {
                            disposableCursor.SetMessage(string.Format("Processing Child Deals: %{0} Completed...", Math.Floor((100.0 * ((double)dn / (double)count)))));
                        }

                        var ts = TransmissionSchedules[dn];

                        if (!ts.IsDirty)
                        {
                            // No need to do any processing around this Schedule.
                            continue;
                        }

                        (bool matches, TransmissionWrapper match) = MatchesToExistingSibling(ts);

                        if (matches)
                        {
                            if (!ts.IsClosed && ts.WasClosedInDB)
                            {
                                match.UnCloseOut();
                            }

                            UpdatedMatchingChildDeal(match, ts);
                            match.MarkAsDirty();

                            if (ts.IsClosed)
                            {
                                dealsToClose.Add(match);
                            }

                            continue;
                        }

                        var newChildWrap = CreateChildDealWrapperFromSchedule(ts);
                        newChildWrap.MarkAsDirty();

                        newChildWrap.Child = lastChildNum++;
                        _modelAction(newChildWrap);
                        _tagUpdates(newChildWrap);


                        // We will NOT add a new Wrap as closed. Logical fallacy.
                        newChildren.Add(newChildWrap);
                    }
                }

                newChildren?.ForEach(x =>
                {
                    x.MTSPaymentEngineContext.IsDoNotRun = true;
                    x.MaturityDateCalculationContext.TurnOffMaturityDateCalculation();
                });

                newChildren?.ForEach(nc => this.AddChildWrapper(nc, false));

                //TC-14683: pde_term & Payment Date error - Child Deals pde_overide = true - pde_term = "DoNotRunPaymentEngine"
                this.ChildWrappers?.ForEach(x =>
                {
                    x.MTSPaymentEngineContext.IsDoNotRun = true;
                    x.MaturityDateCalculationContext.TurnOffMaturityDateCalculation();

                    if (x.DealDate != this.DealDate)
                    {
                        x.DealDate = this.DealDate;
                        x.MarkAsDirty();
                    }
                });

                if (dealsToClose.Any())
                {
                    // Close Deals
                    foreach (var toBeClosed in dealsToClose)
                    {
                        toBeClosed.CloseOut(DateTime.Now);
                    }
                }
            }

            // Since we processed the Transmission Schedules, mark them as Not-Dirty
            this.TransmissionSchedules.ForEach(ts => ts.IsDirty = false);

            return true;
        }

        private static void _modelAction(TransmissionWrapper tw)
        {
            tw.Deal.model = new TransportModelType()
            {
                _Discriminator_ = TransportModelTypeEnum.spread_option,
                _Active_ = true,
                at_cost = generics.DDLVoid.Instance,
                intrinsic = generics.DDLVoid.Instance,
                spread_option = new SpreadOptionModelParams()
                {
                    _Active_ = true,
                    cancelled_flows = new CancelPhysicalFlowDates() { },
                    monthly_threshold = new MonthlyOptionThreshold() { },
                    expiration_date_expr = "rollb(refdate, 1, NERC ^ sat)"
                }
            };
        }

        private static void _tagUpdates(TransmissionWrapper tw)
        {
            tw.SetTagValue(DealTagNames.USPowerTransmissionDealIndicatorTag, "Y");
            tw.SetTagValue(DealTagNames.OtcRegUniqueProductId, "Commodity:Energy:Elec:Transmission");
            tw.SetTagValue(DealTagNames.TransportContactPriceTag, tw.ReservationCharge.ToString());
            tw.SetTagValue(DealTagNames.TransportMaxRate, tw.TransportMaxRate.ToString());
        }

        public override void OptionalDealAndActionSpecificPostAction()
        {
            ApplySnapshot();

            switch (this.ActiveAction)
            {
                case dst.dealentry.dealactions.DealActionEnum.SaveToMemory:
                    this.TransmissionSchedules.ForEach(ts => ts.IsDirty = true);
                    break;
                default:
                    break;
            }

            base.OptionalDealAndActionSpecificPostAction();
        }

        public override void CancelEdit()
        {
            base.CancelEdit();
        }

        #region Custom Charges

        public BindingList<Charge> Charges => new BindingList<Charge>(Deal.custom_charges);

        private List<ITransportElementCustomCharge> _transportElementCharges = null;
        private BindingList<ITransportElementCustomCharge> _elementChargesBindingList = null;

        public BindingList<ITransportElementCustomCharge> TransportElementCharges
        {
            get
            {
                if (_transportElementCharges == null)
                {
                    _transportElementCharges = this.ExtractChargeInfoFromDeal();

                    _elementChargesBindingList = new BindingList<ITransportElementCustomCharge>(_transportElementCharges);
                }

                return _elementChargesBindingList;
            }
        }

        private const string DAILY_AT_ACTUAL_VOLUME = "DAILY_AT_ACTUAL_VOLUME";
        private const string DAILY_AT_CONTRACT_VOLUME = "DAILY_AT_CONTRACT_VOLUME";
        private const string ONE_TIME_CHARGE = "ONE_TIME_CHARGE";
        private const string VOLUMETRIC_ACTUAL_ABOVE_CONTRA = "VOLUMETRIC_ACTUAL_ABOVE_CONTRA";
        private const string VOLUMETRIC_ACTUAL_BELOW_CONTRA = "VOLUMETRIC_ACTUAL_BELOW_CONTRA";

        private List<ITransportElementCustomCharge> ExtractChargeInfoFromDeal()
        {
            var resultSet = new List<ITransportElementCustomCharge>();

            if (this.SingleTransportElement?.custom_charges != null)
            {
                foreach (var c in this.SingleTransportElement.custom_charges)
                {
                    this.AddTransportElementChargeToSet(resultSet, c);
                }
            }

            if (this.Deal.custom_charges != null)
            {
                foreach (var c in this.Deal.custom_charges)
                {
                    this.AddTransportElementChargeToSet(resultSet, c);
                }
            }

            if (resultSet.Count == 0)
            {
                resultSet.Add(new TransportElementCustomCharge()
                {
                    description = string.Empty,
                    type = DAILY_AT_ACTUAL_VOLUME,
                    value = 0.0
                });
            }

            return resultSet;
        }

        private void AddTransportElementChargeToSet(List<ITransportElementCustomCharge> set, Charge c)
        {
            TransportElementCustomCharge newCharge = null;

            if (c.charge_type.daily_at_actual_volume.fixed_price.price > 0.0)
            {
                newCharge = new TransportElementCustomCharge()
                {
                    description = c.description,
                    type = DAILY_AT_ACTUAL_VOLUME,
                    value = c.charge_type.daily_at_actual_volume.fixed_price.price
                };
            }
            else if (c.charge_type.daily_at_contract_volume.fixed_price.price > 0.0)
            {
                newCharge = new TransportElementCustomCharge()
                {
                    description = c.description,
                    type = DAILY_AT_CONTRACT_VOLUME,
                    value = c.charge_type.daily_at_contract_volume.fixed_price.price
                };
            }
            else if (c.charge_type.one_time_charge.amount > 0.0)
            {
                newCharge = new TransportElementCustomCharge()
                {
                    description = c.description,
                    type = ONE_TIME_CHARGE,
                    value = c.charge_type.one_time_charge.amount
                };
            }
            else if (c.charge_type.volumetric_actual_above_contract.fixed_price.price > 0.0)
            {
                newCharge = new TransportElementCustomCharge()
                {
                    description = c.description,
                    type = VOLUMETRIC_ACTUAL_ABOVE_CONTRA,
                    value = c.charge_type.volumetric_actual_above_contract.fixed_price.price
                };
            }
            else if (c.charge_type.volumetric_actual_below_contract.fixed_price.price > 0.0)
            {
                newCharge = new TransportElementCustomCharge()
                {
                    description = c.description,
                    type = VOLUMETRIC_ACTUAL_BELOW_CONTRA,
                    value = c.charge_type.volumetric_actual_below_contract.fixed_price.price
                };
            }

            if (newCharge == null) return; // Must be some other form of charges, erroneously added?

            if (set.Any(tecc => string.Equals(tecc.type, newCharge.type)))
            {
                // Existing charge, must be a duplicate. Skip
                return;
            }

            set.Add(newCharge);
        }

        private bool SetCustomChargesAndReport(TransmissionWrapper wrap, List<ITransportElementCustomCharge> transportElementCustomCharges)
        {
            // First, persist existing charges and then clear.
            var existingCharges = wrap.ExtractChargeInfoFromDeal()
                                                                   .Where(tc => tc.value > 0.00)
                                                                   .ToList();
            
            wrap.SingleTransportElement.custom_charges.Clear();
            wrap.Deal.custom_charges.Clear();

            // Remove the UI-supporting non-real charge which is entered only to allow entry.
            var nonZeroCharges = transportElementCustomCharges.Where(tc => tc.value > 0.00).ToList();
            
            foreach (var tecc in nonZeroCharges)
            {
                var newCharge = GenerateCharge(wrap, tecc);
                
                wrap.Deal.custom_charges.Add(newCharge);
            }

            var anyChanges = nonZeroCharges.Count > existingCharges.Count;
            anyChanges |=  nonZeroCharges.Any(nzc => existingCharges.Any(ec =>
                TransportElementCustomCharge.Changed(nzc, ec)));

            return anyChanges;
        }

        private static Charge GenerateCharge(TransmissionWrapper wrap, ITransportElementCustomCharge tecc)
        {
            var newCharge = new Charge { description = tecc.description };

            if (tecc.type == DAILY_AT_ACTUAL_VOLUME)
            {
                newCharge.charge_type.daily_at_actual_volume = new VolumetricCharge()
                {
                    _Active_ = true,
                    fixed_price = new FixedPriceVolumetricCharge()
                    {
                        // units = wrap.Currency, // The production examples did not have any assignments here. Skipping it for now.
                        currency = new Currency() { _Discriminator_ = CurrencyEnum.deal_currency, _Active_ = true },
                        price = tecc.value
                    },
                    _Discriminator_ = VolumetricChargeEnum.fixed_price
                };
            }

            if (tecc.type == DAILY_AT_CONTRACT_VOLUME)
            {
                newCharge.charge_type.daily_at_contract_volume = new VolumetricCharge()
                {
                    _Active_ = true,
                    fixed_price = new FixedPriceVolumetricCharge()
                    {
                        units = wrap.Currency,
                        currency = new Currency() { _Discriminator_ = CurrencyEnum.deal_currency, _Active_ = true },
                        price = tecc.value
                    },
                    _Discriminator_ = VolumetricChargeEnum.fixed_price
                };
            }

            if (tecc.type == ONE_TIME_CHARGE)
            {
                // TODO: Don't know what to do here yet. [Kemal, July 2024]
            }

            if (tecc.type == VOLUMETRIC_ACTUAL_ABOVE_CONTRA)
            {
                // TODO: Don't know what to do here yet. [Kemal, July 2024]
            }

            if (tecc.type == VOLUMETRIC_ACTUAL_BELOW_CONTRA)
            {
                // TODO: Don't know what to do here yet. [Kemal, July 2024]
            }

            return newCharge;
        }


        // Internal class to cater the info from actual charges to the UI. At the moment, we are ignoring all other charges except FixedPrice charges. If that logic changes, the Charge -> UI class logic and ensuing logic 
        // needs to be modified as well.

        /// <summary>
        /// UI Representation of Transport Element specific charges on US Power Deals
        /// </summary>
        public class TransportElementCustomCharge : ITransportElementCustomCharge
        {
            public string type { get; set; }
            public string description { get; set; }
            public double value { get; set; }

            public static bool Changed(ITransportElementCustomCharge orig, ITransportElementCustomCharge upd)
            {
                if (orig.type != upd.type) return false;

                if (orig.description != upd.description || Math.Abs(orig.value - upd.value) > 0.01) return true;

                return false;
            }
        }


        #endregion

        private string _scheduleTemplate = string.Empty;
        public string ScheduleTemplate
        {            get => _scheduleTemplate;
            set
            {
                if (_scheduleTemplate == value) return;

                _scheduleTemplate = value;
                FirePropertyChangedEvent(nameof(ScheduleTemplate));
            }
        }

        //Not used, always 0
        public int HEStart
        {
            get
            {
                return 0;
            }
            set
            {

            }
        }

        //Not used, always 0
        public int HEEnd
        {
            get
            {
                return 0;
            }
            set
            {
            }
        }

        #region Change Handlers
        public override void FirePropertyChangedEvent(string propertyName)
        {
            if (!FireEvents) return;

            base.FirePropertyChangedEvent(propertyName);
        }

        public string TotalDeliveryVolumeString => string.Format("{0:N3} {1}", TotalDeliveryVolume, SingleTransportElement.volume_unit);

        private double _totalDeliveryVolume = 0.0;
        private const double Tolerance = 0.1;

        public double TotalDeliveryVolume
        {
            get => _totalDeliveryVolume;
            set
            {
                if (Math.Abs(_totalDeliveryVolume - value) < Tolerance) return;

                _totalDeliveryVolume = value;
                FirePropertyChangedEvent(nameof(TotalDeliveryVolume));
            }
        }

        public void RefreshTWView()
        {
            FirePropertyChangedEvent(nameof(StartDate));
            FirePropertyChangedEvent(nameof(EndDate));
            FirePropertyChangedEvent(nameof(VolumePerHour));
            FirePropertyChangedEvent(nameof(TotalDeliveryVolumeString));
            FirePropertyChangedEvent(nameof(GlobalPaymentTerm));
        }

        #endregion

        #region Read/Write access

        protected override void AddReadOnlyProperties(List<string> readOnlyProperties)
        {
            readOnlyProperties.Add("TotalDeliveryVolumeString");

            base.AddReadOnlyProperties(readOnlyProperties);
        }
        #endregion

        #region IRunPayment Members

        public bool RunMTSPaymentCalculation(out string error)
        {
            error = string.Empty;
            return true;
        }

        public (string paymentTerm, string paymentDateExpr) PaymentContextResult()
        {
            this.MTSPaymentEngineContext.PaymentTermGroup = Constants.PdeUSPowerGroupName;

            TransmissionWrapper wrap = (TransmissionWrapper)base.MTSPaymentEngineContext.RunPaymentEngine(out string error);

            MTSPaymentEngineContext.PaymentTerm = wrap.MTSPaymentEngineContext.PaymentTerm;

            return (paymentTerm: wrap.MTSPaymentEngineContext.PaymentTerm, paymentDateExpr: wrap.Deal.payment_date_expr);
        }

        public string OverriddenPaymentContextResultPDExpr()
        {
            this.MTSPaymentEngineContext.PaymentTermGroup = Constants.PdeUSPowerGroupName;

            TransmissionWrapper wrap =
                (TransmissionWrapper)base.MTSPaymentEngineContext.RunPaymentEngine<TransmissionWrapper>(out string error);

            return wrap.Deal.payment_date_expr;
        }

        #endregion

        #region IAssetSelectorRequester Members

        private IAssetSelectorHandler _usPowerAssetHandler;

        private IAssetSelectorHandler GetPowerAssetHandler()
        {
            if (_usPowerAssetHandler == null)
            {
                _usPowerAssetHandler = new USPowerAssetSelectorHandler(
                    TransmissionAssetsHelper.GetUSPowerAssetsFilteredForLocationOnly().AsReadOnly()
                );

                _usPowerAssetHandler.HideFilter(USPowerAssetSelectorHandler.Frequency);
                _usPowerAssetHandler.HideFilter(USPowerAssetSelectorHandler.SubType);
                _usPowerAssetHandler.HideFilter(USPowerAssetSelectorHandler.ScheduleType);
                _usPowerAssetHandler.HideFilter(USPowerAssetSelectorHandler.DART);
                _usPowerAssetHandler.HideFilter(USPowerAssetSelectorHandler.PhysFin);
            }

            return _usPowerAssetHandler;
        }

        public IAssetSelectorHandler GetDefaultAssetHandler(string field)
        {
            return GetPowerAssetHandler();
        }

        public IEnumerable<IAssetSelectorHandler> GetAvailableAssetHandlers(string field)
        {
            return new[] { GetPowerAssetHandler() };
        }

        #endregion

        #region Validation
        public const string TRANSPORT_ELEMENT_GENERATE_SCOPE = "TransportElementGenerateScope";

        protected override void RegisterBusinessRules()
        {
            base.RegisterBusinessRules();

            //Errors --------------------------------------------------
            base.AddValidationRule(
               CommonRules.RequiredStringDateNumber,
               new RuleArgs("StartDate", true, RuleSeverity.Error),
               ValidationManager.DB_SCOPE, GENERATE_SCOPE);

            base.AddValidationRule(
               CommonRules.RequiredStringDateNumber,
               new RuleArgs("EndDate", true, RuleSeverity.Error),
               ValidationManager.DB_SCOPE, GENERATE_SCOPE);

            base.AddValidationRule(
               CommonRules.RequiredValidator,
               new RuleArgs(CounterpartyHook, true, RuleSeverity.Error),
               ValidationManager.IMMEDIATE_SCOPE);

            base.AddValidationRule(
               CommonRules.RequiredStringDateNumber,
               new RuleArgs("EnabledBlocksType", true, RuleSeverity.Error),
               ValidationManager.DB_SCOPE, GENERATE_SCOPE);

            base.AddValidationRule(
               CommonRules.RequiredStringDateNumber,
               new RuleArgs("DealContainer.DealCommon.deal_date", true, RuleSeverity.Error),
               ValidationManager.DB_SCOPE);

            base.AddValidationRule(
               CommonRules.RequiredStringDateNumber,
               new RuleArgs("Deal.deal_type", true, RuleSeverity.Error),
               ValidationManager.DB_SCOPE);

            base.AddValidationRule(
               CommonRules.RequiredStringDateNumber,
               new RuleArgs("Deal.currency", true, RuleSeverity.Error),
               ValidationManager.DB_SCOPE);

            base.AddValidationRule(
              CommonRules.RequiredStringDateNumber,
              new RuleArgs("VolumeUnit", true, RuleSeverity.Error),
              ValidationManager.DB_SCOPE, GENERATE_SCOPE);

            base.AddValidationRule(
               CommonRules.RequiredStringDateNumber,
               new RuleArgs("ServiceLevel", true, RuleSeverity.Error),
               ValidationManager.DB_SCOPE);

            base.AddValidationRule(
               CommonRules.RequiredStringDateNumber,
               new RuleArgs("FercProductType", true, RuleSeverity.Error),
               ValidationManager.DB_SCOPE);

            base.AddValidationRule(
                ConditionalServiceLevelValidator,
                new RuleArgs("ServiceFirm", true, RuleSeverity.Error),
                ValidationManager.DB_SCOPE);

            base.AddValidationRule(
                ConditionalServiceLevelValidator,
                new RuleArgs("UnitFirm", true, RuleSeverity.Error),
                ValidationManager.DB_SCOPE);
        }
        #endregion

        #region Transport Elements

        private TransportElement CopyTransportElement(TransportElement existingElement)
        {
            TransportElement newItem = new TransportElement();
            newItem.volume = existingElement.volume;
            newItem.volume_unit = existingElement.volume_unit;
            newItem.loss_rate_percentage = existingElement.loss_rate_percentage;
            newItem.delivery_point = existingElement.delivery_point;
            newItem.receiving_point = existingElement.receiving_point;

            ObservableCommodity commod = new ObservableCommodity(existingElement.fuel_payment_type.in_cash.observable);
            if (commod.ThisCommodity != null)
            {
                newItem.fuel_payment_type.in_cash.observable = commod.CreateObservableCommodity();
            }
            newItem.fuel_payment_type.in_cash.price = existingElement.fuel_payment_type.in_cash.price;
            newItem.fuel_payment_type._Discriminator_ = existingElement.fuel_payment_type._Discriminator_;

            return newItem;

        }

        public void InitializeTransportElementsFromDeal()
        {
            var existingElements = new List<TransportElement>();

            foreach (var existingElement in this.Deal.elements)
            {
                existingElements.Add(existingElement);
            }

            using (new DynamicPropertyObjectEventSuppressor(this))
            {
                Deal.elements.Clear();

                foreach (var existingElement in existingElements)
                {
                    var element = CopyTransportElement(existingElement);
                    element.delivery_point = this.Deal.delivery_point;
                    element.receiving_point = this.Deal.receiving_point;

                    Deal.elements.Add(element);
                }
            }
        }

        public void InitializeNewTransportElementsCollection()
        {
            using (new DynamicPropertyObjectEventSuppressor(this))
            {
                Deal.elements.Clear();

                if (!string.IsNullOrEmpty(this.Deal.delivery_point) && !string.IsNullOrEmpty(this.Deal.receiving_point))
                {
                    TransportElement element = new TransportElement
                    {
                        delivery_point = this.Deal.delivery_point,
                        receiving_point = this.Deal.receiving_point
                    };

                    Deal.elements.Add(element);
                }
            }
        }

        public void GenerateTransportElements(TransmissionWrapper sourceWrapper)
        {
            using (new DynamicPropertyObjectEventSuppressor(this))
            {
                Deal.elements.Clear();

                if (!string.IsNullOrEmpty(sourceWrapper.DeliveryPoint) && !string.IsNullOrEmpty(sourceWrapper.ReceivingPoint))
                {
                    TransportElement element =
                        CopyTransportElement(sourceWrapper.SingleTransportElement as TransportElement);
                    element.delivery_point = sourceWrapper.Deal.delivery_point;
                    element.receiving_point = sourceWrapper.Deal.receiving_point;
                    Deal.elements.Add(element);
                }
            }
        }

        public bool DisplayTransportElementColumn(string columnName)
        {
            return true;
        }

        public bool DisplayTransportActualColumn(string columnName)
        {
            return true;
        }

        #endregion Transport Elements

        public EIDManager EIDManager => throw new NotImplementedException();
        
        

        #region Action Module

        protected override void CreateActionItems()
        {
            base.CreateActionItems();

            ActionItem paymentActionItem = new ActionItem(ActionNames.ACTION_PAYMENT, "Determine Payment Dates", Resources.calendar, this, false);
            this.ActionItemManager.AddActionItemAtTheEnd(paymentActionItem);
        }

        public override bool IsActionAutoRun(string name)
        {
            if (name == ActionNames.ACTION_PAYMENT)
            {
                return !IsInDB;
            }

            return base.IsActionAutoRun(name);
        }

        public override ActionItemState GetActionState(string name)
        {
            if (name == ActionNames.ACTION_PAYMENT)
            {
                return DoesPaymentInformationMatch() ? ActionItemState.Current : ActionItemState.Stale;
            }

            return base.GetActionState(name);
        }

        public override bool FireAction(string name, List<string> errorList)
        {
            if (name == ActionNames.ACTION_PAYMENT)
            {
                if (!RunMTSPaymentCalculation(out string error))
                {
                    errorList.Add(string.Format("Action Item Error: {0}", error));
                    return false;
                }

                // FirePropertyChangedEvent(string.Empty);
                return true;
            }

            return base.FireAction(name, errorList);
        }

        public bool DoesPaymentInformationMatch()
        {
            return true;
        }

        #endregion

        #region Snapshot

        public void TakeSnapshot()
        {
            _snapShotAlreadyApplied = false;
            
            var csb = new StringBuilder();
            for (int i = 0; i < this._transportElementCharges.Count; i++)
            {
                var tec = this._transportElementCharges[i];

                if (i > 0)
                {
                    csb.Append(TransportConstants.CustomChargeDelimiter);
                }

                var saveTECC = new TransportElementCustomCharge()
                {
                    type = tec.type,
                    description = tec.description,
                    value = tec.value
                };

                var teccAsJson = JsonConvert.SerializeObject(saveTECC);
                csb.Append(teccAsJson);
            }

            var snapshot = new TransmissionWrapperSnapshot()
            {
                CustomCharges = csb.ToString(),
                GlobalComment = this.GlobalComment,
                DeliveryPoint = this.DeliveryPoint,
                EnabledBlocksType = this.EnabledBlocksType.ToString(),
                EndDate = this.EndDate,
                LossRatePercentage = this.LossRatePercentage,
                GlobalPaymentTerm = this.GlobalPaymentTerm,
                ReceivingPoint = this.ReceivingPoint,
                ReservationCharge = this.Deal.reservation_charge,
                ReservationChargeUnit = this.ReservationChargeUnit,
                StartDate = this.StartDate,
                TransportMaxRate = this.TransportMaxRate,
                TotalDeliveryVolume = this.TotalDeliveryVolume,
                VolumePerHour = this.VolumePerHour
            };

            var asJson = JsonConvert.SerializeObject(snapshot);

            SetTagValue(TransportConstants.GenerationalTag, asJson);

            _log.Info($"Snapshot taken and stored in tag: {asJson}");
        }

        private bool _snapShotAlreadyApplied = false;

        private void ApplySnapshot()
        {
            try
            {
                if (_snapShotAlreadyApplied) return;

                // Only apply the snapshot from the Main deal, Child 0
                if (Child > 0) return;

                using (new DynamicPropertyObjectEventSuppressor(this))
                {
                    var snapshot = GetSnapshot();

                    if (snapshot == null) return;

                    this.DeliveryPoint = snapshot.DeliveryPoint;
                    this.EnabledBlocksType = snapshot.EnabledBlocksType.ToEnumOrDefault<IntradayEnabledBlocksEnum>(IntradayEnabledBlocksEnum.peak);
                    this.EndDate = snapshot.EndDate;
                    this.GlobalComment = snapshot.GlobalComment;
                    this.LossRatePercentage = snapshot.LossRatePercentage;
                    this.GlobalPaymentTerm = snapshot.GlobalPaymentTerm;
                    this.ReceivingPoint = snapshot.ReceivingPoint;
                    this.ReservationCharge = snapshot.ReservationCharge;
                    this.ReservationChargeUnit = snapshot.ReservationChargeUnit;
                    this.StartDate = snapshot.StartDate;
                    this.TransportMaxRate = snapshot.TransportMaxRate;
                    this.VolumePerHour = snapshot.VolumePerHour;

                    var splitTSC = snapshot.CustomCharges.Split(TransportConstants.CustomChargeDelimiter);

                    var transportElementCustomCharges = new List<ITransportElementCustomCharge>();

                    foreach (var teccJson in splitTSC)
                    {
                        var tecc = JsonConvert.DeserializeObject<TransportElementCustomCharge>(teccJson);
                        transportElementCustomCharges.Add(tecc);
                    }

                    SetCustomChargesAndReport(this, transportElementCustomCharges);
                    _snapShotAlreadyApplied = true;
                }

                FirePropertyChangedEvent(string.Empty);
            }
            catch (Exception ex)
            {
                _log.Error(ex);
            }
        }

        public TransmissionWrapperSnapshot GetSnapshot()
        {
            if (this.Child != 0) return null;

            var asJson = GetTagValue(TransportConstants.GenerationalTag);

            if (string.IsNullOrEmpty(asJson))
            {
                _log.Warn("No snapshot found in tag.");
                return null;
            }

            try
            {
                _log.Info($"Deserializing snapshot from tag: {asJson}");

                var snapshot = JsonConvert.DeserializeObject<TransmissionWrapperSnapshot>(asJson);

                return snapshot;
            }
            catch (Exception ex)
            {
                _log.Error(asJson, ex);
                return null;
            }
        }

        #endregion Snapshot
    }
}
